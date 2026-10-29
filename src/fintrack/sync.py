"""Sync Engine: pull each Item from Plaid, then write Raw + Ledger in one transaction.

Items sync independently, so one bank failing never blocks the others. Syncing is
idempotent: replaying the same cursor rewrites the same rows.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import date

from . import keychain
from .db import transaction, utcnow
from .enrich import enrich_all
from .plaid import (
    AccountRecord,
    PlaidClient,
    PlaidError,
    PlaidResponse,
    TransactionChanges,
    TransactionRecord,
    fetch_transaction_changes,
    parse_account,
)

log = logging.getLogger(__name__)

HISTORY_COMPLETE = "HISTORICAL_UPDATE_COMPLETE"

_lock = threading.Lock()


class SyncInProgress(RuntimeError):
    pass


def is_running() -> bool:
    return _lock.locked()


@dataclass
class ItemResult:
    item_id: int
    institution: str | None
    accounts: int = 0
    added: int = 0
    modified: int = 0
    removed: int = 0
    transactions_status: str | None = None
    error: str | None = None


@dataclass
class SyncResult:
    run_id: int
    status: str  # success | partial | failed
    items: list[ItemResult]


def run_sync(
    conn: sqlite3.Connection,
    client: PlaidClient,
    *,
    triggered_by: str,
    item_ids: Iterable[int] | None = None,
) -> SyncResult:
    if not _lock.acquire(blocking=False):
        raise SyncInProgress("a sync is already running")
    try:
        with transaction(conn):
            run_id = conn.execute(
                "INSERT INTO sync_runs (triggered_by, started_at) VALUES (?, ?)", (triggered_by, utcnow())
            ).lastrowid
        items = conn.execute("SELECT * FROM items ORDER BY id").fetchall()
        if item_ids is not None:
            wanted = set(item_ids)
            items = [item for item in items if item["id"] in wanted]
        results = [_sync_item(conn, client, item, run_id) for item in items]
        try:
            enrich_all(conn)
        except Exception:  # a classification bug must not undo the sync; the next run re-derives everything
            log.exception("enrichment failed after sync run %s", run_id)
        failures = sum(r.error is not None for r in results)
        status = "success" if not failures else "failed" if failures == len(results) else "partial"
        with transaction(conn):
            conn.execute(
                "UPDATE sync_runs SET status = ?, finished_at = ?, summary = ? WHERE id = ?",
                (status, utcnow(), json.dumps([asdict(r) for r in results], ensure_ascii=False), run_id),
            )
        return SyncResult(run_id, status, results)
    finally:
        _lock.release()


def sync_new_item(
    conn: sqlite3.Connection,
    client: PlaidClient,
    item_id: int,
    *,
    interval: float = 30,
    attempts: int = 40,
    sleep: Callable[[float], None] = time.sleep,
) -> SyncResult | None:
    """Right after linking, Plaid is still pulling up to 2 years of history: poll until it lands.

    Plaid would announce this with a webhook, but a localhost app can't receive one.
    """
    result = None
    for attempt in range(attempts):
        if attempt:
            sleep(interval)
        try:
            result = run_sync(conn, client, triggered_by="link", item_ids=[item_id])
        except SyncInProgress:
            continue
        item = result.items[0] if result.items else None
        if item is None or item.error or item.transactions_status == HISTORY_COMPLETE:
            break
    return result


def _sync_item(conn: sqlite3.Connection, client: PlaidClient, item: sqlite3.Row, run_id: int) -> ItemResult:
    result = ItemResult(item_id=item["id"], institution=item["institution_name"])
    try:
        token = keychain.get_access_token(item["external_id"])
        if token is None:
            # Without its token an Item can't even be repaired in update mode; it has to be linked again.
            return _fail(conn, result, "error", "access token not found in Keychain")
        accounts = client.get_accounts(token)
        changes = fetch_transaction_changes(client, token, item["sync_cursor"])
        with transaction(conn):
            _apply(conn, item["id"], run_id, accounts, changes)
    except PlaidError as e:
        status = "login_required" if e.error_code == "ITEM_LOGIN_REQUIRED" else "error"
        return _fail(conn, result, status, str(e))
    except Exception as e:  # keep the other Items syncing; the traceback goes to the log
        log.exception("sync failed for item %s", item["id"])
        return _fail(conn, result, "error", f"{type(e).__name__}: {e}")
    result.accounts = len(accounts.body["accounts"])
    result.added, result.modified, result.removed = len(changes.added), len(changes.modified), len(changes.removed)
    result.transactions_status = changes.update_status
    return result


def _fail(conn: sqlite3.Connection, result: ItemResult, status: str, error: str) -> ItemResult:
    result.error = error
    with transaction(conn):
        conn.execute("UPDATE items SET status = ?, last_error = ? WHERE id = ?", (status, error, result.item_id))
    return result


def _apply(
    conn: sqlite3.Connection, item_id: int, run_id: int, accounts: PlaidResponse, changes: TransactionChanges
) -> None:
    now = utcnow()
    conn.executemany(
        "INSERT INTO raw_events (sync_run_id, item_id, endpoint, payload, received_at) VALUES (?, ?, ?, ?, ?)",
        [(run_id, item_id, "/accounts/get", accounts.raw, now)]
        + [(run_id, item_id, "/transactions/sync", page, now) for page in changes.pages],
    )

    # /accounts/get is authoritative; sync pages only fill in accounts it didn't list.
    records = {a.external_id: a for a in changes.accounts}
    records.update((a.external_id, a) for a in map(parse_account, accounts.body["accounts"]))
    for record in records.values():
        _upsert_account(conn, item_id, record, now)

    account_ids = {
        row["external_id"]: row["id"]
        for row in conn.execute("SELECT external_id, id FROM accounts WHERE item_id = ?", (item_id,))
    }
    for txn in changes.added + changes.modified:
        if txn.account_external_id not in account_ids:
            raise ValueError(f"transaction {txn.external_id} references unknown account {txn.account_external_id}")
        _upsert_transaction(conn, account_ids[txn.account_external_id], txn, now)
    conn.executemany(
        "UPDATE transactions SET removed_at = ?, updated_at = ? WHERE external_id = ? AND removed_at IS NULL",
        [(now, now, external_id) for external_id in changes.removed],
    )

    # An empty next_cursor means Plaid had nothing ready yet: keep the old cursor and try again later.
    conn.execute(
        """
        UPDATE items
        SET status = 'active', last_error = NULL, last_synced_at = ?, transactions_status = ?,
            sync_cursor = COALESCE(NULLIF(?, ''), sync_cursor)
        WHERE id = ?
        """,
        (now, changes.update_status, changes.next_cursor, item_id),
    )


def _upsert_account(conn: sqlite3.Connection, item_id: int, account: AccountRecord, now: str) -> None:
    account_id = conn.execute(
        """
        INSERT INTO accounts (item_id, external_id, name, official_name, mask, type, subtype, currency,
                              current_cents, available_cents, limit_cents, balance_as_of, created_at)
        VALUES (:item_id, :external_id, :name, :official_name, :mask, :type, :subtype, :currency,
                :current_cents, :available_cents, :limit_cents, :now, :now)
        ON CONFLICT (external_id) DO UPDATE SET
            name = excluded.name, official_name = excluded.official_name, mask = excluded.mask,
            type = excluded.type, subtype = excluded.subtype, currency = excluded.currency,
            current_cents = excluded.current_cents, available_cents = excluded.available_cents,
            limit_cents = excluded.limit_cents, balance_as_of = excluded.balance_as_of
        RETURNING id
        """,
        {**asdict(account), "item_id": item_id, "now": now},
    ).fetchone()["id"]
    conn.execute(
        """
        INSERT INTO balance_snapshots (account_id, as_of, current_cents, available_cents, limit_cents, captured_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (account_id, as_of) DO UPDATE SET
            current_cents = excluded.current_cents, available_cents = excluded.available_cents,
            limit_cents = excluded.limit_cents, captured_at = excluded.captured_at
        """,
        (account_id, date.today().isoformat(), account.current_cents, account.available_cents, account.limit_cents, now),
    )


_TRANSACTION_FIELDS = (
    "external_id", "pending", "pending_external_id", "amount_cents", "currency",
    "transaction_date", "authorized_date", "posted_date", "merchant_name", "description",
    "original_description", "merchant_entity_id", "payment_channel",
    "pfc_primary", "pfc_detailed", "pfc_confidence", "logo_url", "website",
)  # fmt: skip

_UPSERT_TRANSACTION = f"""
INSERT INTO transactions (account_id, {", ".join(_TRANSACTION_FIELDS)}, first_seen_at, updated_at)
VALUES (:account_id, {", ".join(f":{name}" for name in _TRANSACTION_FIELDS)}, :now, :now)
ON CONFLICT (external_id) DO UPDATE SET
    account_id = excluded.account_id,
    {", ".join(f"{name} = excluded.{name}" for name in _TRANSACTION_FIELDS if name != "external_id")},
    removed_at = NULL,
    updated_at = excluded.updated_at
"""


def _upsert_transaction(conn: sqlite3.Connection, account_id: int, txn: TransactionRecord, now: str) -> None:
    conn.execute(
        _UPSERT_TRANSACTION,
        {**asdict(txn), "account_id": account_id, "pending": int(txn.pending), "now": now},
    )
