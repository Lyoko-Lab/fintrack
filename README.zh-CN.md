# Fintrack

[English](README.md) | 简体中文

运行在你 Mac 上的个人财务系统：每天自动同步银行交易，合并成统一账本，自动区分收入、支出和转账，在本地网页上提供首页指标、交易流、收支分析、信用卡还款日和现金流预测。设计见 [docs/DESIGN.zh-CN.md](docs/DESIGN.zh-CN.md)。

当前进度：**Phase 2**。已有自动同步、转账配对、自动分类加你自己的分类规则，以及信用卡账单。网页有总览、交易流、分析、规则和账户五个页面，界面有英文和中文两种语言。

## 准备

需要 [uv](https://docs.astral.sh/uv/) 和 Node.js：

```bash
uv sync
```

```bash
npm --prefix web install
```

```bash
npm --prefix web run build
```

前端代码有改动时，要重新运行最后这条构建命令。

## 1. 注册 Plaid，录入密钥

1. 在 <https://dashboard.plaid.com/signup> 注册，用途选 **Personal use**。2026-04-15 之后新建的 team 才能用免费的 Trial 套餐（可连 Chase、BOA 等 OAuth 银行）。
2. 在 Dashboard 的 **Developers → Keys** 里找到 `client_id` 和 Sandbox `secret`。
3. 把它们写进 macOS Keychain。命令后面不要带值，运行后按提示粘贴再回车。粘贴时屏幕上不显示字符，值也不会留在 shell 历史或磁盘文件里：

```bash
uv run fintrack secrets set PLAID_CLIENT_ID
```

```bash
uv run fintrack secrets set PLAID_SECRET_SANDBOX
```

## 2. 在 Sandbox 里验证

用命令行一次跑完（连接测试银行 → 拉取数据 → 打印结果）：

```bash
uv run fintrack sandbox-link
```

或者走浏览器流程，和以后连接真实银行的步骤一样：

```bash
uv run fintrack serve
```

打开 <http://127.0.0.1:8787>，在「账户」页点「连接新银行」，选 First Platypus Bank，用户名填 `user_transactions_dynamic`，密码随便填。

## 3. 连接真实银行（Production）

### 在 Plaid Dashboard 开通正式环境

1. 打开 <https://dashboard.plaid.com/trial-plan> 提交 Trial 套餐申请，等 Plaid 通知开通，可能要几个工作日。开通前，Dashboard 里和正式环境有关的页面都会显示 Not available。**不要点「Get production access」**：那是付费套餐的申请，一旦提交就再也回不到 Trial。
2. 在 [Link 自定义页](https://dashboard.plaid.com/link/data-transparency-v5)的 Data Transparency 部分选一个用途：**Track and manage your finances**，然后点 Publish。不选用途，正式环境打不开 Link。
3. 在 [OAuth institutions](https://dashboard.plaid.com/settings/compliance/us-oauth-institutions) 页确认 Bank of America、Chase、American Express 可用。Trial 套餐不用填安全问卷和公司资料，页面上显示资料未完成属于正常情况。
4. 在 **Developers → Keys** 复制 Production `secret`。`client_id` 两个环境通用，不用重新录入。

### 切换到正式环境

```bash
uv run fintrack secrets set PLAID_SECRET_PRODUCTION
```

```bash
printf 'FINTRACK_ENV=production\n' > .env
```

然后按第 4 节注册后台服务，或者用 `uv run fintrack serve` 在前台运行。侧栏底部显示「真实账户」，就说明切换成功了。

### 连接银行

打开 <http://127.0.0.1:8787>，在「账户」页点「连接新银行」，依次连接 Bank of America、Chase、American Express，每家只连一次：

- 银行的登录页在弹出窗口里打开。如果被浏览器拦截，允许 127.0.0.1 弹出窗口。银行密码只在银行自己的页面里输入，Fintrack 拿不到。
- **在银行的授权页面里勾选所有卡**：BOA 勾借记卡和信用卡，Chase 勾 3 张，Amex 勾 2 张。
- Chase 会让你选授权期限，没有默认值，建议选 1 year。
- 连接成功后会自动拉取 2 年历史，几分钟后就能在「交易流」里看到。

授权会过期：BOA 和 Amex 每 12 个月要重新授权一次，Chase 按你选的期限。到期后「账户」页会显示「需要重新登录」，点「重新登录」修复即可。

> **Trial 套餐最多 10 个连接，按累计数计算，删除后不返还。** 连接掉线时用页面上的「重新登录」修复，不要删除后重新添加。
>
> **Keychain 里 service 为 `fintrack` 的条目保存着各银行的 access token。** 删掉后只能重新连接，会消耗额度。

## 4. 让它在后台常驻

注册为 macOS 后台服务后，登录时自动启动，崩溃后自动重启，每天 06:00 自动同步。Mac 睡过了 06:00，醒来后会自动补上：

```bash
uv run fintrack service install
```

之后直接打开 <http://127.0.0.1:8787>。用 `uv run fintrack service status` 查看服务状态，用 `uv run fintrack service uninstall` 移除。日志在 `data/logs/server.log`。服务运行期间不要再手动运行 `fintrack serve`，否则两者会抢同一个端口。

更新时运行：

```bash
uv run fintrack update
```

它会切换到最新的稳定[版本](https://github.com/Lyoko-Lab/fintrack/releases)、安装新增的依赖、构建前端、让服务用新代码重启，最后确认服务稳定运行。数据库结构如有变化，服务启动时会自动迁移。也可以自己选版本：

```bash
uv run fintrack update 0.2.0
```

```bash
uv run fintrack update --dev
```

前一条切换到指定版本；后一条跟随 GitHub 上的最新代码（开发版），你在本机提交的改动也会一起部署。`0.3.0-rc.1` 这样的候选版只有在你点名时才会安装。

以下情况它会在动手前停下：本地有未提交的改动；没有明确指定就要把开发版退回到旧的发布版；目标版本比数据库最近一次迁移还旧，那个版本没法在你的数据上运行。前端构建失败时，正在运行的网页保持原样。

## 界面语言

网页界面有英文和简体中文两种。在侧栏底部切换（手机上在顶栏右端），浏览器会记住你的选择；第一次打开时跟随浏览器的语言。命令行、日志和 API 的提示信息都是英文。

## 常用命令

| 命令 | 作用 |
|---|---|
| `uv run fintrack serve` | 在前台启动网页 <http://127.0.0.1:8787>（含每日自动同步） |
| `uv run fintrack sync` | 立即同步所有银行 |
| `uv run fintrack status` | 查看连接状态，以及各账户的交易笔数和日期范围（不显示名称、尾号、余额） |
| `uv run fintrack secrets list` | 查看哪些密钥已配置（不显示内容） |
| `uv run fintrack service install` | 注册为开机自启的后台服务 |
| `uv run fintrack update` | 更新到最新的稳定版，重新构建前端并重启服务（`update 0.2.0` 指定版本，`update --dev` 跟随最新代码） |
| `uv run fintrack --version` | 查看当前版本 |
| `uv run pytest` | 运行后端测试 |
| `uv run python scripts/seed_demo.py` | 生成两年的合成交易，写入 `.dev-data/`，供开发时代替真实数据 |
| `FINTRACK_ENV=sandbox FINTRACK_DATA_DIR=.dev-data FINTRACK_PORT=8788 uv run fintrack serve` | 用合成数据启动演示服务（8788 端口） |
| `npm --prefix web run dev` | 前端开发模式：<http://localhost:5173>，支持热更新，`/api` 转发到 8788 端口的演示服务 |

数据在 `data/` 目录（已加入 `.gitignore`），Sandbox 和 Production 各用一个数据库文件，测试数据不会混进真实账本。

隐私设计见 [docs/DESIGN.zh-CN.md](docs/DESIGN.zh-CN.md) 第 8 节：真实数据默认只留在本机，用 Claude Code 开发时也不会读取它（规则在 [CLAUDE.md](CLAUDE.md)）。

## 发布版本

版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)，每个版本改了什么写在 [CHANGELOG.zh-CN.md](CHANGELOG.zh-CN.md)。发布步骤：

1. 修改 `pyproject.toml` 和 `web/package.json` 里的版本号（候选版分别写成 `0.3.0rc1` 和 `0.3.0-rc.1`），然后运行 `uv lock` 和 `npm --prefix web install`，让锁文件同步。
2. 在中英两份更新日志里，把 "Unreleased" 标题改成版本号和日期，再新开一个空的 "Unreleased" 小节。
3. 提交，打标签并推送标签：

```bash
git tag -a v0.2.0 -m "Fintrack 0.2.0"
```

```bash
git push origin main v0.2.0
```

之后 Release 工作流会跑测试和构建，核对标签和两处版本号一致，再用更新日志里的那一节作为说明发布 GitHub Release（`v0.3.0-rc.1` 这样的标签会标为预发布）。

## 许可证

Fintrack 是自由软件，以 [GNU Affero 通用公共许可证 v3.0](LICENSE)（`AGPL-3.0-only`）发布。你可以使用、研究、修改和分享它；如果分发修改后的版本，或者让别人通过网络使用修改后的版本，就要按同一许可证向他们提供源代码。
