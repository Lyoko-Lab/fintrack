# Fintrack

个人财务系统：每天自动同步银行交易，合并成统一账本，自动区分收入、支出和转账，提供首页指标和交易流。设计见 [docs/DESIGN.md](docs/DESIGN.md)。

当前进度：**Phase 1 · MVP**（自动同步、转账配对、规则分类，以及 React 前端的总览、交易流和账户页）。

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

1. 在 Dashboard 里拿到 Production `secret`，写入 Keychain：

   ```bash
   uv run fintrack secrets set PLAID_SECRET_PRODUCTION
   ```

2. 复制 `.env.example` 为 `.env`，把 `FINTRACK_ENV` 改成 `production`。
3. 运行 `uv run fintrack serve`，在「账户」页依次连接 Bank of America、Chase、American Express，每家只连一次。在银行的授权页面里勾选所有卡。

> **Trial 套餐最多 10 个连接，按累计数计算，删除后不返还。** 连接掉线时用页面上的「重新登录」修复，不要删除后重新添加。
>
> **Keychain 里 service 为 `fintrack` 的条目保存着各银行的 access token。** 删掉后只能重新连接，会消耗额度。

## 4. 让它在后台常驻

注册为 macOS 后台服务后，登录时自动启动，崩溃后自动重启，每天 06:00 自动同步。Mac 睡过了 06:00，醒来后会自动补上：

```bash
uv run fintrack service install
```

之后直接打开 <http://127.0.0.1:8787>。用 `uv run fintrack service status` 查看服务状态，用 `uv run fintrack service uninstall` 移除。日志在 `data/logs/server.log`。服务运行期间不要再手动运行 `fintrack serve`，否则两者会抢同一个端口。

## 常用命令

| 命令 | 作用 |
|---|---|
| `uv run fintrack serve` | 在前台启动网页 <http://127.0.0.1:8787>（含每日自动同步） |
| `uv run fintrack sync` | 立即同步所有银行 |
| `uv run fintrack status` | 查看连接、账户、交易数 |
| `uv run fintrack secrets list` | 查看哪些密钥已配置（不显示内容） |
| `uv run fintrack service install` | 注册为开机自启的后台服务 |
| `uv run pytest` | 运行后端测试 |
| `npm --prefix web run dev` | 前端开发模式：<http://localhost:5173>，支持热更新，`/api` 转发到 8787 端口 |

数据在 `data/` 目录（已加入 `.gitignore`），Sandbox 和 Production 各用一个数据库文件，测试数据不会混进真实账本。
