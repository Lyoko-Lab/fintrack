# Fintrack 设计文档

个人财务系统：每天自动同步 BOA、Chase、Amex 的全部交易，合并成统一账本，提供收支分析和基于 Claude 的问答。本地部署，网页界面。

**已确认的决定（2026-10-28）**：数据源用 Plaid Trial；后端 Python，前端 React；历史数据拉 2 年；朋友转回的 AA 款冲减对应分类的支出，不算收入。暂不纳入投资账户。

## 1. 产品功能

| 功能 | 说明 |
|---|---|
| **Overview** | 首页：Income MTD、Spending MTD、Net Cash Position 三张指标卡（附"比上月同期"），下面接 Activity |
| **Activity** | 7 个账户的交易按日期合并成一条流水；转账照常显示，加 ⇄ 标记，但不计入收支 |
| **Insights** | 按日、周、月、年看现金流趋势、支出结构、同期对比和变化来源 |
| **Ask Fintrack** | 用 Claude 对全部交易做对话式分析 |
| **Accounts** | 余额、连接状态、重新授权 |
| **Rules** | 分类规则；你手动改分类时可以一键生成 |

指标口径：

- **Income MTD**：本月 1 日至今，`flow_type = income` 的金额之和
- **Spending MTD**：本月 1 日至今，`flow_type = expense` 的流出之和，再减去退款（支出类别里的正数）。待入账交易也计入
- **Net Cash Position**：存款账户当前余额之和，减去信用卡当前欠款之和
- **对比口径**：收入和支出与"上月同期"比（上月 1 日到上月同一天，月底日期自动截到上月最后一天）。净现金头寸与"上月同日"比。聚合商只提供当前余额，所以过去某天的头寸用倒推计算：当前头寸减去那天之后所有已入账交易的金额之和。两个已关联账户之间的转账一出一进，正好抵消。上月值为零或负数时，不显示百分比

## 2. 架构

```
BOA · Chase · Amex
   │  OAuth（银行密码只在 Plaid 弹窗里输入，Fintrack 拿不到）
   ▼
Plaid API
   │  每日拉取 /transactions/sync（cursor 增量）
   ▼
┌─ Fintrack backend · single process · 127.0.0.1 ──────────
│  Scheduler ──► Sync Engine ──► Connectors (Plaid | CSV)
│                    │
│                    ▼
│  Enrichment: normalize → transfer match → categorize ──► Claude API
│                    │
│                    ▼
│  SQLite: raw │ ledger │ enrichment │ analytics views
│                    ▲
│  Analytics API ────┤
│  Ask Agent ────────┘ read-only SQL ──────────────────► Claude API
└──────────────┬────────────────────────────────────────────
               │  REST + SSE
        Browser (React SPA)
```

- **单进程**：一个 FastAPI 进程同时提供 API、托管前端、跑定时任务，交给 launchd 管理。只监听 127.0.0.1，并校验 Host 头，防止 DNS rebinding。
- **SQLite（WAL 模式）**：表结构写在编号的 SQL 迁移文件里，版本号记在 `PRAGMA user_version`。数据访问直接写 SQL，不用 ORM：分析视图本身就是 SQL，Ask 时 Claude 查的也是这些视图。
- **定时拉取，不用 webhook**：本地没有公网地址，收不到 Plaid 的 webhook。

## 3. 数据源：Plaid Trial

- 一次银行登录算一个 Item。Trial 共 10 个，**按累计数计算，删除后不返还**。连接掉线一律用 Link 的 update mode 修复，不删除重连。
- Link 参数：`products=["transactions"]`，`optional_products=["liabilities"]`，`transactions.days_requested=730`（Item 创建后不能再改）。不申请 `auth`，所以系统里不会有完整卡号和 routing number。
- 桌面浏览器里，OAuth 会在弹窗中完成，不需要 `redirect_uri`。
- Sandbox 和 Production 用两个独立的数据库文件（`data/fintrack-sandbox.db` 和 `data/fintrack-production.db`）。
- Connector 只负责取数和标准化，输出与数据源无关的记录（`AccountRecord`、`TransactionRecord`）。以后可以按银行换成 Teller，或用 CSV 导入补 2 年以前的历史。

## 4. 存储

| 层 | 表 | 规则 |
|---|---|---|
| Raw | `raw_events` | 每个 API 响应的原文，只追加不修改 |
| Ledger | `items` `accounts` `transactions` `balance_snapshots` `sync_runs` | 清洗后的统一账本 |
| Enrichment | `categories` `transaction_enrichment` `transaction_overrides` | 自动分类每次同步后全量重算；用户修改单独存放，同步绝不覆盖 |
| Views | `v_ledger` | Overview、Activity、Insights、Ask 都只读这个视图，保证各处口径一致 |

约定：

- **金额**：整数美分，正负号按你的视角，流入为正、流出为负。Plaid 原始数据正好相反，入库时翻转。
- **日期**：`transaction_date` 取 `authorized_date`，没有时用 `posted_date`。所有统计都按它算，所以 10/31 刷卡、11/2 入账的交易算在 10 月。
- **时间格式**：时间戳用 UTC ISO-8601，日期用 `YYYY-MM-DD`；余额快照按本地日期，每个账户每天一行。
- **不硬删除**：Plaid 撤回的交易（例如 pending 交易正式入账后）只记 `removed_at`。
- **机密不进数据库**：Plaid access token 和所有 API key 都存在 macOS Keychain 里（service 为 `fintrack`）。
- **分类决定收支类型**：每个分类属于 expense、income 或 transfer 之一，`flow_type` 跟随分类。所以用户只需要改分类，比如改成"账户间转账"就等于标记为转账。支出类别里的正数是退款，会冲减支出。
- **待入账交易正式入账后**：Plaid 会用一笔新的正式交易替换它，用户在原来那笔上的修改会自动沿用到新交易上。

## 5. 同步

- **何时触发**：服务进程里有一个调度线程（`scheduler.py`），每 5 分钟检查一次：如果从最近一个 06:00 到现在还没有成功同步过，就跑一次。所以 Mac 睡过了 06:00，醒来后几分钟内会补上。失败后重试，但间隔至少 30 分钟。另外，「账户」页有「立即同步」按钮；新连接一家银行后会自动轮询，直到 2 年历史拉齐。
- **常驻运行**：`fintrack service install` 会把服务注册为 macOS LaunchAgent，登录时自动启动，崩溃后自动重启。它直接运行项目虚拟环境里的 `fintrack serve`，不依赖 uv 或 shell。
- **每个 Item 独立执行**：先调 `/accounts/get`，再用 `/transactions/sync` 一直翻页到底，然后在**一个数据库事务**里写 Raw 层、更新账户和余额快照、写入交易、标记已移除的交易、推进 cursor。中途崩溃时什么都不会写入，下次从旧 cursor 重来。
- 翻页途中遇到 `TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION`：从这一轮起始的 cursor 整体重来。
- 返回 `NOT_READY` 时 `next_cursor` 为空：保留原来的 cursor，下次重试。
- 遇到 `ITEM_LOGIN_REQUIRED`：把该 Item 标成 `login_required`，页面上提供「重新登录」（走 update mode）。
- 同一进程内同一时间只跑一个同步；重复执行结果相同（幂等）。

## 6. 分类与分析

### 自动分类规则（Phase 1，`enrich.py`）

分类体系有两级、约 60 个类别，定义在迁移文件 `0002_enrichment.sql` 里，只有最底层的类别可以给交易使用。规则从上往下匹配，命中第一条即停止：

1. **非现金账户**（贷款、投资）上的交易：归为转账，不进入收支
2. **个人转账类应用**（Zelle、Venmo、Cash App、Apple Cash，以及没有识别出商户的 PayPal）：转入算"AA 与报销收回"，冲减支出；转出算"个人转账"，计入支出。通过 PayPal 付款给商户的交易仍归到该商户的分类
3. **信用卡还款**，从两端识别：卡上收到的还款（如 "AUTOMATIC PAYMENT - THANK YOU"），以及存款账户付出的还款（如 "CHASE CREDIT CRD AUTOPAY"、"AMERICAN EXPRESS ACH PMT"、"payment to CRD 7781"）
4. **存款账户的入账**：描述含工资、退税或利息关键词时，分别归为工资、退税、利息收入
5. **Plaid 分类**：按前缀映射到自有分类，兼容 PFC v1 和 v2。之后再检查资金方向：流出不可能是收入；信用卡上收到的钱是退款或返现，也不是收入
6. **兜底**：存款账户的流入归为其他收入，信用卡的流入归为返现，流出归为未分类

**转账配对**：在两个不同的已关联账户之间，找出金额相等、方向相反、入账日期相差不超过 5 天的一对交易，配对后都标为转账，并互相记录对方。配对条件是至少一侧已被识别为转账，另一侧也有转账迹象，以免把同金额的退款误配进来。有多个候选时，优先选同样被识别为转账的那一笔。贷款还款的处理方式是：如果当初那笔购买是由我们没有关联的放贷方出资的（房贷、车贷、学贷、先买后付），还款就算支出；其余情况只是借来的钱在账户间流动，算转账。

### 之后（Phase 2）

- 分类优先级扩展为：用户手动修改 > 用户规则 > 商户记忆 > 上述自动规则 > Claude 批量分类（用 structured outputs 保证只返回有效类别）。置信度低的进入待确认列表；你改分类时可以一键生成规则。
- Plaid 的分类只能作为参考。Sandbox 实测中，`Sweetgreen inc payroll ppd id` 是工资入账，却被归为 `FOOD_AND_DRINK_RESTAURANT`；信用卡还款 "Payment Thank You" 被归为 `INCOME`。因此 `flow_type` 和分类都要结合 `original_description` 来判断。
- 分析支持日、周、月、年四种粒度。对比默认用同期对比（本月 1–28 日 vs 上月 1–28 日），另有环比、同比、近 3 个月平均，以及支出变化主要来自哪些分类。

## 7. Ask Fintrack（Phase 3）

- 给 Claude 一个只读 SQL 工具（只能查分析视图，只读连接，限制返回行数和执行时间），再加几个汇总工具；回答流式输出，对话记录存在本地。
- 表结构、口径、分类体系和账户列表放在 system prompt 里，用 prompt caching 缓存。
- 只有查询返回的结果会离开本机。
- 模型默认 `claude-opus-5-5`；分类任务可以换成更便宜的 `claude-haiku-5-5`。

## 8. 分期

- [x] Phase 0 代码：Plaid 连接器、同步引擎、Raw 和 Ledger 存储、连接调试页、CLI
- [x] Phase 0 Sandbox 验收（2026-10-28）：7 个账户、316 笔交易入库，正负号已对照原始数据核实，Link 可正常打开
- [ ] Phase 0 真实银行验收：连接 BOA、Chase、Amex，确认 OAuth 可用、2 年历史都拿到（Sandbox 只有约 1 个月数据，无法验证历史深度）
- [x] Phase 1 MVP 代码（2026-10-28）：定时同步与 launchd 服务、Enrichment（收支判定、转账配对、规则分类、用户修改）、React 前端（Overview、Activity、Accounts）
- [ ] Phase 1 校准：连上真实银行后，用真实描述检查信用卡还款识别和转账配对
- [ ] Phase 2：Claude 自动分类、改分类的反馈流程、Insights
- [ ] Phase 3：Ask Fintrack
- [ ] 之后：识别订阅和周期扣费、异常交易提醒、还款日提醒（Liabilities）、预算、投资账户
