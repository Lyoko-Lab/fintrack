# Fintrack · Claude Code 工作约定

个人财务系统。设计见 docs/DESIGN.md，用法见 README.md。和用户交流用中文。

## 隐私：真实财务数据不进入对话

用户已经连接了真实的银行账户。Claude Code 读到的一切（文件内容、命令输出、截图、网页）都会发送给 Anthropic，所以开发时只接触代码和 Sandbox 测试数据：

- 不读取 `data/` 下的任何文件，包括正式和 Sandbox 数据库、`-wal`/`-shm` 文件和日志；也不通过 sqlite3、Python 或 `fintrack.db` 查询账本。
- 不读取 Keychain 里 service 为 `fintrack` 的条目。
- 不访问正式环境的服务（127.0.0.1:8787）：不 curl，不在浏览器面板或 Chrome 里打开，不截图。
- 只运行输出不含个人信息的命令：`fintrack status`（连接状态、各账户的交易笔数和日期范围）、`fintrack secrets list`、`fintrack service status`、`uv run pytest`。新增读取真实数据的命令时，它的输出也必须守住这条。
- 验证界面只用合成的演示数据：先运行 `uv run python scripts/seed_demo.py`，再启动 `.claude/launch.json` 里的 `fintrack-demo`（端口 8788）和 `web-dev`（端口 5173，`/api` 转发到 8788）。
- 需要真实数据才能判断的事，请用户自己在网页上查看或修正，不要为此读取数据。分类的校准也是这样：用户在网页上修正，修正可以生成规则。

`.claude/settings.json` 的 deny 规则和 `.claude/hooks/private_data_guard.py` 钩子会兜底拦截，但兜底拦不住所有写法，以上面的约定为准。

## 开发

- 后端测试：`uv run pytest`。前端类型检查：`npm --prefix web run typecheck`。
- `web/dist` 就是正式服务正在用的前端，构建它会立即影响用户在用的页面。验证能否构建时，输出到临时目录：`npm --prefix web exec -- vite build web --outDir <临时目录>`。部署新版本（构建 `web/dist`、重启服务）要先征得用户同意。
- 金额用整数美分，流入为正。改表结构时新增一个编号迁移文件，不修改已有的迁移。
