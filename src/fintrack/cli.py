"""Command line entry point: `uv run fintrack <command>`."""

from __future__ import annotations

import argparse
import getpass
import logging
import sys
from importlib.metadata import version

from . import items, keychain, service, sync, update
from .config import load_settings
from .db import open_db
from .plaid import SANDBOX_INSTITUTION, PlaidClient, PlaidError, PlaidNotConfigured


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fintrack", description="Fintrack, a personal finance tracker")
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('fintrack')}")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="run the web app at http://127.0.0.1:8787")
    commands.add_parser("sync", help="sync every connected bank now")
    commands.add_parser("status", help="show connections, accounts and transaction counts")
    sandbox = commands.add_parser("sandbox-link", help="(Sandbox only) connect a test bank without the browser")
    sandbox.add_argument("--username", default="user_transactions_dynamic", help="Plaid Sandbox test user")
    secrets = commands.add_parser("secrets", help="manage secrets in the macOS Keychain")
    secret_actions = secrets.add_subparsers(dest="action", required=True)
    secret_set = secret_actions.add_parser("set", help="store a secret: paste it at the prompt, input is hidden")
    secret_set.add_argument("name", choices=keychain.USER_SECRETS)
    # A value typed on the command line would land in shell history; accept it only to refuse it with guidance.
    secret_set.add_argument("value", nargs="?", help=argparse.SUPPRESS)
    secret_actions.add_parser("list", help="show which secrets are set, never their values")
    service_command = commands.add_parser("service", help="run the web app in the background from login (macOS launchd)")
    service_command.add_argument("action", choices=("install", "uninstall", "status"))
    commands.add_parser("update", help="pull the latest code from GitHub, rebuild, and restart the background service")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    handlers = {
        "serve": _serve,
        "sync": _sync,
        "status": _status,
        "sandbox-link": _sandbox_link,
        "secrets": _secrets,
        "service": _service,
        "update": _update,
    }
    try:
        return handlers[args.command](args)
    except (PlaidNotConfigured, PlaidError, service.ServiceError, update.UpdateError) as e:
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
        print("sandbox-link only works with FINTRACK_ENV=sandbox", file=sys.stderr)
        return 1
    client = PlaidClient.from_settings(settings)
    conn = open_db(settings.db_path)
    institution_id, institution_name = SANDBOX_INSTITUTION
    public_token = client.create_sandbox_public_token(args.username, institution_id)
    item_id = items.save_item(conn, client, public_token, institution_id, institution_name)
    print(f"Connected {institution_name} (item #{item_id}); waiting for Plaid to prepare the history…")
    _print_result(sync.sync_new_item(conn, client, item_id, interval=5, attempts=24))
    return 0


def _status(args: argparse.Namespace) -> int:
    # Only what it takes to tell whether syncing works: no account names, masks, balances or transactions.
    # Claude Code is allowed to run this command (see CLAUDE.md), so its output must stay free of personal data.
    settings = load_settings()
    conn = open_db(settings.db_path)
    print(f"Environment: {settings.env}    Database: {settings.db_path}")
    for item in conn.execute("SELECT * FROM items ORDER BY id"):
        print(
            f"\n[{item['id']}] {item['institution_name']}  status {item['status']}  "
            f"history {item['transactions_status']}  last sync {item['last_synced_at']}"
        )
        if item["last_error"]:
            print(f"    error: {item['last_error']}")
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
            statement = ("  has statement" if a["has_statement"] else "  no statement") if a["type"] == "credit" else ""
            print(f"    {a['type']}/{a['subtype'] or '-'}  {a['transaction_count']} transactions  {span}{statement}")
    print("\nAccount names, masks, balances and transactions are not shown here; see the web app.")
    return 0


def _secrets(args: argparse.Namespace) -> int:
    if args.action == "list":
        for name in keychain.USER_SECRETS:
            print(f"{name:<26}{'set' if keychain.get_secret(name) else '—'}")
        return 0
    if args.value is not None:
        print(
            "Don't type a secret on the command line: it would stay in your shell history. Run only\n"
            f"    uv run fintrack secrets set {args.name}\n"
            "and paste it at the prompt, then press Enter (nothing shows while you paste).",
            file=sys.stderr,
        )
        return 2
    value = getpass.getpass(f"{args.name} (paste, then press Enter; input is hidden): ").strip()
    if not value:
        print("Nothing entered; cancelled", file=sys.stderr)
        return 1
    keychain.set_secret(args.name, value)
    print(f"Saved to the Keychain (service=fintrack, account={args.name})")
    return 0


def _service(args: argparse.Namespace) -> int:
    if args.action == "install":
        settings = load_settings()
        plist = service.install(settings)
        log = settings.data_dir / "logs" / "server.log"
        print(f"Background service registered: {plist}\nWeb app: http://127.0.0.1:{settings.port}    Log: {log}")
    elif args.action == "uninstall":
        service.uninstall()
        print("Background service removed")
    else:
        print(f"Background service: {service.status()}")
    return 0


def _update(args: argparse.Namespace) -> int:
    settings = load_settings()
    running = update.update(settings)
    print(f"Updated to {running}. Web app: http://127.0.0.1:{settings.port}")
    return 0


def _print_result(result: sync.SyncResult | None) -> None:
    if result is None:
        print("No sync ran: another sync is in progress")
        return
    print(f"Sync #{result.run_id}: {result.status}")
    for r in result.items:
        if r.error:
            print(f"  {r.institution}: failed, {r.error}")
        else:
            print(
                f"  {r.institution}: {r.accounts} accounts, {r.added} added, {r.modified} modified, "
                f"{r.removed} removed, history {r.transactions_status}"
            )
