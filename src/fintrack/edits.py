"""The user's own edits to a transaction: its category and a note.

Stored in transaction_overrides, which neither sync nor enrichment overwrites. Setting
a field to None reverts it (category back to the automatic one, note removed).
"""

from __future__ import annotations

import sqlite3

from .db import transaction, utcnow

EDITABLE_FIELDS = ("category_id", "note")


class UnknownTransaction(LookupError):
    pass


class InvalidEdit(ValueError):
    pass


def edit_transaction(conn: sqlite3.Connection, transaction_id: int, changes: dict[str, str | None]) -> None:
    if unknown := set(changes) - set(EDITABLE_FIELDS):
        raise InvalidEdit(f"cannot edit {sorted(unknown)}")
    if "note" in changes:
        changes["note"] = (changes["note"] or "").strip() or None
    with transaction(conn):
        if conn.execute("SELECT 1 FROM transactions WHERE id = ? AND removed_at IS NULL", (transaction_id,)).fetchone() is None:
            raise UnknownTransaction(transaction_id)
        if changes.get("category_id") is not None:
            assignable = conn.execute(
                """
                SELECT NOT EXISTS (SELECT 1 FROM categories k WHERE k.parent_id = c.id)
                FROM categories c WHERE c.id = ?
                """,
                (changes["category_id"],),
            ).fetchone()
            if not assignable or not assignable[0]:
                raise InvalidEdit(f"{changes['category_id']!r} is not an assignable category")

        current = conn.execute(
            "SELECT category_id, note FROM transaction_overrides WHERE transaction_id = ?", (transaction_id,)
        ).fetchone()
        merged = {field: current[field] if current else None for field in EDITABLE_FIELDS} | changes
        if merged["category_id"] is None and merged["note"] is None:
            conn.execute("DELETE FROM transaction_overrides WHERE transaction_id = ?", (transaction_id,))
            return
        conn.execute(
            """
            INSERT INTO transaction_overrides (transaction_id, category_id, note, updated_at) VALUES (?, ?, ?, ?)
            ON CONFLICT (transaction_id) DO UPDATE SET
                category_id = excluded.category_id, note = excluded.note, updated_at = excluded.updated_at
            """,
            (transaction_id, merged["category_id"], merged["note"], utcnow()),
        )
