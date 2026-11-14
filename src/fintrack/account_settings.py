"""The user's settings for an account: a nickname, and whether it counts in totals.

Stored in account_settings, which sync never writes; v_accounts applies them. A nickname of None
goes back to the bank's name, and an account with neither setting loses its row.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .db import transaction, utcnow

EDITABLE_FIELDS = ("nickname", "excluded")
MAX_NICKNAME_LENGTH = 60


class UnknownAccount(LookupError):
    pass


class InvalidSetting(ValueError):
    pass


def edit_account(conn: sqlite3.Connection, account_id: int, changes: dict[str, Any]) -> None:
    if unknown := set(changes) - set(EDITABLE_FIELDS):
        raise InvalidSetting(f"cannot set {sorted(unknown)}")
    if "nickname" in changes:
        changes["nickname"] = (changes["nickname"] or "").strip() or None
        if changes["nickname"] and len(changes["nickname"]) > MAX_NICKNAME_LENGTH:
            raise InvalidSetting(f"An account's name can be at most {MAX_NICKNAME_LENGTH} characters")
    if "excluded" in changes:
        changes["excluded"] = int(bool(changes["excluded"]))
    with transaction(conn):
        if conn.execute("SELECT 1 FROM accounts WHERE id = ?", (account_id,)).fetchone() is None:
            raise UnknownAccount(account_id)
        current = conn.execute("SELECT nickname, excluded FROM account_settings WHERE account_id = ?", (account_id,)).fetchone()
        merged = {"nickname": current["nickname"] if current else None, "excluded": current["excluded"] if current else 0} | changes
        if merged["nickname"] is None and not merged["excluded"]:
            conn.execute("DELETE FROM account_settings WHERE account_id = ?", (account_id,))
            return
        conn.execute(
            """
            INSERT INTO account_settings (account_id, nickname, excluded, updated_at) VALUES (?, ?, ?, ?)
            ON CONFLICT (account_id) DO UPDATE SET
                nickname = excluded.nickname, excluded = excluded.excluded, updated_at = excluded.updated_at
            """,
            (account_id, merged["nickname"], merged["excluded"], utcnow()),
        )


_ACCOUNTS = """
SELECT id, item_id, name, bank_name, nickname, excluded, official_name, mask, type, subtype, currency,
       current_cents, available_cents, limit_cents, balance_as_of, institution_name
FROM v_accounts
"""


def accounts(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every account as the user sees it, bank by bank, deposit accounts first."""
    return [dict(row) for row in conn.execute(_ACCOUNTS + "ORDER BY item_id, type != 'depository', bank_name")]


def account(conn: sqlite3.Connection, account_id: int) -> dict[str, Any] | None:
    row = conn.execute(_ACCOUNTS + "WHERE id = ?", (account_id,)).fetchone()
    return dict(row) if row else None
