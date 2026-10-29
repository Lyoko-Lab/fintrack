"""Write ledger rows straight into the database, for tests that start after the sync step."""

from __future__ import annotations

import itertools
import sqlite3

_ids = itertools.count(1)


def add_account(db: sqlite3.Connection, name: str, type: str, *, mask: str = "0000", current_cents: int = 0,
                institution: str = "Bank of America") -> int:  # fmt: skip
    item = db.execute("SELECT id FROM items WHERE institution_name = ?", (institution,)).fetchone()
    item_id = item["id"] if item else db.execute(
        "INSERT INTO items (external_id, institution_name, created_at) VALUES (?, ?, '2026-10-01T00:00:00Z') RETURNING id",
        (f"item-{next(_ids)}", institution),
    ).fetchone()["id"]
    return db.execute(
        """
        INSERT INTO accounts (item_id, external_id, name, mask, type, current_cents, created_at)
        VALUES (?, ?, ?, ?, ?, ?, '2026-10-01T00:00:00Z') RETURNING id
        """,
        (item_id, f"acc-{next(_ids)}", name, mask, type, current_cents),
    ).fetchone()["id"]


def add_txn(db: sqlite3.Connection, account_id: int, amount_cents: int, day: str, description: str, *,
            pfc: str | None = None, merchant: str | None = None, pending: bool = False, posted: str | None = None,
            external_id: str | None = None, pending_external_id: str | None = None) -> int:  # fmt: skip
    return db.execute(
        """
        INSERT INTO transactions (account_id, external_id, pending, pending_external_id, amount_cents, currency,
                                  transaction_date, posted_date, merchant_name, description, original_description,
                                  pfc_detailed, first_seen_at, updated_at)
        VALUES (?, ?, ?, ?, ?, 'USD', ?, ?, ?, ?, ?, ?, '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z')
        RETURNING id
        """,
        (account_id, external_id or f"txn-{next(_ids)}", int(pending), pending_external_id, amount_cents, day,
         posted or day, merchant, merchant or description, description, pfc),
    ).fetchone()["id"]  # fmt: skip
