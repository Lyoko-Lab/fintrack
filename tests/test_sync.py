from __future__ import annotations

import sqlite3
from typing import Any

from plaid_fakes import FakeItem, FakePlaid, account, page, txn

from fintrack import keychain
from fintrack.sync import run_sync, sync_new_item

CHECKING = account(
    "acc-checking", type="depository", subtype="checking", current=3200.10, available=3150.00, limit=None,
    name="Adv Plus Banking", mask="0001",
)  # fmt: skip
CARD = account("acc-card")


def link(
    db: sqlite3.Connection,
    plaid: FakePlaid,
    pages: dict[str | None, dict[str, Any]],
    *,
    external_id: str = "item-1",
    token: str = "access-1",
    name: str = "Chase",
    accounts: list[dict[str, Any]] | None = None,
) -> int:
    plaid.items[token] = FakeItem(accounts or [CARD], pages)
    keychain.set_access_token(external_id, token)
    return db.execute(
        "INSERT INTO items (external_id, institution_name, created_at) VALUES (?, ?, '2026-10-28T00:00:00Z') RETURNING id",
        (external_id, name),
    ).fetchone()["id"]


def scalar(db: sqlite3.Connection, sql: str, *args: Any) -> Any:
    return db.execute(sql, args).fetchone()[0]


def test_first_sync_builds_the_ledger_and_keeps_raw_pages(db, plaid):
    item_id = link(db, plaid, accounts=[CHECKING, CARD], pages={
        None: page(added=[txn("t1", 5.75, "2026-10-02"),
                          txn("t2", -2500, "2026-10-01", account_id="acc-checking", merchant=None)],
                   next_cursor="c1", has_more=True),
        "c1": page(added=[txn("t3", 19.99, "2026-10-03", authorized="2026-10-02")], next_cursor="c2"),
    })  # fmt: skip

    result = run_sync(db, plaid.client(), triggered_by="test")

    assert result.status == "success"
    amounts = dict(db.execute("SELECT external_id, amount_cents FROM transactions").fetchall())
    assert amounts == {"t1": -575, "t2": 250000, "t3": -1999}
    item = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    assert (item["sync_cursor"], item["status"], item["transactions_status"]) == ("c2", "active", "HISTORICAL_UPDATE_COMPLETE")
    endpoints = [row[0] for row in db.execute("SELECT endpoint FROM raw_events ORDER BY id")]
    assert endpoints == ["/accounts/get", "/transactions/sync", "/transactions/sync"]
    card = db.execute("SELECT current_cents, limit_cents FROM accounts WHERE external_id = 'acc-card'").fetchone()
    assert tuple(card) == (84520, 500000)
    assert scalar(db, "SELECT COUNT(*) FROM balance_snapshots") == 2


def test_a_posted_transaction_replaces_its_pending_version(db, plaid):
    link(db, plaid, pages={
        None: page(added=[txn("p1", 64.00, "2026-10-26", pending=True)], next_cursor="c1"),
        "c1": page(added=[txn("t1", 64.00, "2026-10-28", authorized="2026-10-26", pending_id="p1")],
                   removed=["p1"], next_cursor="c2"),
    })  # fmt: skip
    client = plaid.client()

    run_sync(db, client, triggered_by="test")
    run_sync(db, client, triggered_by="test")

    visible = db.execute("SELECT id, pending, transaction_date FROM v_ledger").fetchall()
    assert [(row["pending"], row["transaction_date"]) for row in visible] == [(0, "2026-10-26")]
    assert scalar(db, "SELECT pending_external_id FROM transactions WHERE external_id = 't1'") == "p1"
    assert scalar(db, "SELECT removed_at IS NOT NULL FROM transactions WHERE external_id = 'p1'") == 1


def test_replaying_a_sync_does_not_duplicate_transactions(db, plaid):
    link(db, plaid, pages={None: page(added=[txn("t1", 5.75, "2026-10-02")], next_cursor="c1")})
    client = plaid.client()

    run_sync(db, client, triggered_by="test")
    db.execute("UPDATE items SET sync_cursor = NULL")
    run_sync(db, client, triggered_by="test")

    assert scalar(db, "SELECT COUNT(*) FROM transactions") == 1


def test_mutation_during_pagination_restarts_from_the_first_cursor(db, plaid):
    link(db, plaid, pages={
        None: page(added=[txn("t1", 1, "2026-10-01")], next_cursor="c1", has_more=True),
        "c1": page(added=[txn("t2", 2, "2026-10-02")], next_cursor="c2"),
    })  # fmt: skip
    plaid.fail_next("/transactions/sync", "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION", cursor="c1")

    result = run_sync(db, plaid.client(), triggered_by="test")

    assert result.status == "success"
    cursors = [body.get("cursor") for path, body in plaid.requests if path == "/transactions/sync"]
    assert cursors == [None, "c1", None, "c1"]
    assert scalar(db, "SELECT COUNT(*) FROM transactions") == 2


def test_a_failed_page_leaves_the_ledger_and_cursor_untouched(db, plaid):
    item_id = link(db, plaid, pages={
        None: page(added=[txn("t1", 1, "2026-10-01")], next_cursor="c1", has_more=True),
        "c1": page(added=[txn("t2", 2, "2026-10-02")], next_cursor="c2"),
    })  # fmt: skip
    plaid.fail_next("/transactions/sync", "INTERNAL_SERVER_ERROR", cursor="c1")

    result = run_sync(db, plaid.client(), triggered_by="test")

    assert result.status == "failed"
    assert scalar(db, "SELECT COUNT(*) FROM transactions") == 0
    item = db.execute("SELECT sync_cursor, status FROM items WHERE id = ?", (item_id,)).fetchone()
    assert tuple(item) == (None, "error")


def test_one_bank_needing_login_does_not_block_the_others(db, plaid):
    link(db, plaid, pages={None: page(added=[txn("t1", 5, "2026-10-01")], next_cursor="c1")})
    link(db, plaid, pages={None: page(next_cursor="a1")}, external_id="item-amex", token="access-amex",
         name="American Express", accounts=[account("acc-amex", name="Gold Card", mask="1009")])  # fmt: skip
    plaid.fail_next("/accounts/get", "ITEM_LOGIN_REQUIRED", access_token="access-amex")

    result = run_sync(db, plaid.client(), triggered_by="test")

    assert result.status == "partial"
    statuses = dict(db.execute("SELECT institution_name, status FROM items").fetchall())
    assert statuses == {"Chase": "active", "American Express": "login_required"}
    assert scalar(db, "SELECT COUNT(*) FROM transactions") == 1


def test_a_new_item_is_polled_until_its_history_arrives(db, plaid):
    item_id = link(db, plaid, pages={None: page(next_cursor="", status="NOT_READY")})
    waits = []

    def wait(seconds: float) -> None:
        waits.append(seconds)
        plaid.items["access-1"].pages[None] = page(added=[txn("t1", 5, "2026-10-01")], next_cursor="c1")

    result = sync_new_item(db, plaid.client(), item_id, interval=30, sleep=wait)

    assert waits == [30]
    assert result.items[0].transactions_status == "HISTORICAL_UPDATE_COMPLETE"
    assert scalar(db, "SELECT sync_cursor FROM items") == "c1"
    assert scalar(db, "SELECT COUNT(*) FROM transactions") == 1
