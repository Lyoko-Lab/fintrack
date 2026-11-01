"""Command line entry point: `uv run fintrack <command>`."""

from __future__ import annotations

import argparse
import getpass
import logging
import sys

from . import items, keychain, service, sync
from .config import load_settings
from .db import open_db
from .plaid import SANDBOX_INSTITUTION, PlaidClient, PlaidError, PlaidNotConfigured


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fintrack", description="Fintrack 个人财务系统")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="启动网页服务 http://127.0.0.1:8787")
    commands.add_parser("sync", help="立即同步所有已连接的银行")
    commands.add_parser("status", help="查看连接、账户和交易概况")
    sandbox = commands.add_parser("sandbox-link", help="（仅 Sandbox）不经浏览器连接一家测试银行")
    sandbox.add_argument("--username", default="user_transactions_dynamic", help="Plaid Sandbox 测试用户名")
    secrets = commands.add_parser("secrets", help="管理 macOS Keychain 中的密钥")
    secret_actions = secrets.add_subparsers(dest="action", required=True)
    secret_set = secret_actions.add_parser("set", help="写入一个密钥：运行后按提示粘贴，输入不回显")
    secret_set.add_argument("name", choices=keychain.USER_SECRETS)
    # A value typed on the command line would land in shell history; accept it only to refuse it with guidance.
    secret_set.add_argument("value", nargs="?", help=argparse.SUPPRESS)
    secret_actions.add_parser("list", help="查看哪些密钥已配置（不显示内容）")
    service_command = commands.add_parser("service", help="把网页服务注册为开机自启的后台服务（macOS launchd）")
    service_command.add_argument("action", choices=("install", "uninstall", "status"))

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    handlers = {
        "serve": _serve,
        "sync": _sync,
        "status": _status,
        "sandbox-link": _sandbox_link,
        "secrets": _secrets,
        "service": _service,
    }
    try:
        return handlers[args.command](args)
    except (PlaidNotConfigured, PlaidError, service.ServiceError) as e:
        print(e, file=sys.stderr)
        return 1


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .app import create_app

    settings = load_settings()
    uvicorn.run(create_app(settings), host="127.0.0.1", port=settings.port)
    return 0


def _sync(args: argparse.Namespace) -> int:
    settings = load_settings()
    client = PlaidClient.from_settings(settings)
    result = sync.run_sync(open_db(settings.db_path), client, triggered_by="cli")
    _print_result(result)
    return 0 if result.status == "success" else 1


def _sandbox_link(args: argparse.Namespace) -> int:
    settings = load_settings()
    if settings.env != "sandbox":
        print("sandbox-link 只能在 FINTRACK_ENV=sandbox 时使用", file=sys.stderr)
        return 1
    client = PlaidClient.from_settings(settings)
    conn = open_db(settings.db_path)
    institution_id, institution_name = SANDBOX_INSTITUTION
    public_token = client.create_sandbox_public_token(args.username, institution_id)
    item_id = items.save_item(conn, client, public_token, institution_id, institution_name)
    print(f"已连接 {institution_name}（item #{item_id}），等 Plaid 准备好历史数据…")
    _print_result(sync.sync_new_item(conn, client, item_id, interval=5, attempts=24))
    return 0


def _status(args: argparse.Namespace) -> int:
    # Only what it takes to tell whether syncing works: no account names, masks, balances or transactions.
    # Claude Code is allowed to run this command (see CLAUDE.md), so its output must stay free of personal data.
    settings = load_settings()
    conn = open_db(settings.db_path)
    print(f"环境：{settings.env}    数据库：{settings.db_path}")
    for item in conn.execute("SELECT * FROM items ORDER BY id"):
        print(
            f"\n[{item['id']}] {item['institution_name']}  状态 {item['status']}  "
            f"历史 {item['transactions_status']}  上次同步 {item['last_synced_at']}"
        )
        if item["last_error"]:
            print(f"    错误：{item['last_error']}")
        accounts = conn.execute(
            """
            SELECT a.type, a.subtype, COUNT(t.id) AS transaction_count,
                   MIN(t.transaction_date) AS first_date, MAX(t.transaction_date) AS last_date,
                   EXISTS (SELECT 1 FROM card_statements s WHERE s.account_id = a.id) AS has_statement
            FROM accounts a
            LEFT JOIN transactions t ON t.account_id = a.id AND t.removed_at IS NULL
            WHERE a.item_id = ?
            GROUP BY a.id
            ORDER BY a.type, a.subtype, a.id
            """,
            (item["id"],),
        )
        for a in accounts:
            span = f"{a['first_date']} ~ {a['last_date']}" if a["transaction_count"] else "—"
            # Whether the bank gave a statement, not what is on it.
            statement = ("  有账单信息" if a["has_statement"] else "  无账单信息") if a["type"] == "credit" else ""
            print(f"    {a['type']}/{a['subtype'] or '-'}  交易 {a['transaction_count']} 笔  {span}{statement}")
    print("\n这里不显示账户名称、尾号、余额和交易明细，请在网页上查看。")
    return 0


def _secrets(args: argparse.Namespace) -> int:
    if args.action == "list":
        for name in keychain.USER_SECRETS:
            print(f"{name:<26}{'已配置' if keychain.get_secret(name) else '—'}")
        return 0
    if args.value is not None:
        print(
            "密钥不要写在命令里，否则会留在 shell 历史中。请只运行：\n"
            f"    uv run fintrack secrets set {args.name}\n"
            "然后在提示处粘贴并回车（粘贴时屏幕上不显示字符）。",
            file=sys.stderr,
        )
        return 2
    value = getpass.getpass(f"{args.name}（粘贴后回车，输入不回显）: ").strip()
    if not value:
        print("没有输入内容，已取消", file=sys.stderr)
        return 1
    keychain.set_secret(args.name, value)
    print(f"已写入 Keychain（service=fintrack, account={args.name}）")
    return 0


def _service(args: argparse.Namespace) -> int:
    if args.action == "install":
        settings = load_settings()
        plist = service.install(settings)
        print(f"已注册后台服务：{plist}\n网页：http://127.0.0.1:{settings.port}    日志：{settings.data_dir / 'logs' / 'server.log'}")
    elif args.action == "uninstall":
        service.uninstall()
        print("已移除后台服务")
    else:
        print(f"后台服务：{service.status()}")
    return 0


def _print_result(result: sync.SyncResult | None) -> None:
    if result is None:
        print("没有执行同步：另一个同步正在进行")
        return
    print(f"同步 #{result.run_id}：{result.status}")
    for r in result.items:
        if r.error:
            print(f"  {r.institution}：失败，{r.error}")
        else:
            print(
                f"  {r.institution}：{r.accounts} 个账户，新增 {r.added} 笔、修改 {r.modified} 笔、"
                f"移除 {r.removed} 笔，历史状态 {r.transactions_status}"
            )
