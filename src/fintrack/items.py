"""Bank logins ("Items"): linking new ones and repairing existing ones in update mode."""

from __future__ import annotations

import sqlite3

from . import keychain
from .db import transaction, utcnow
from .plaid import PlaidClient


class UnknownItem(LookupError):
    pass


class MissingAccessToken(LookupError):
    pass


def create_link_token(conn: sqlite3.Connection, client: PlaidClient, item_id: int | None = None) -> str:
    """A token for linking a new bank, or, given item_id, for repairing that one in update mode."""
    if item_id is None:
        return client.create_link_token()
    row = conn.execute("SELECT external_id FROM items WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise UnknownItem(item_id)
    token = keychain.get_access_token(row["external_id"])
    if token is None:
        raise MissingAccessToken(item_id)
    return client.create_link_token(access_token=token)


def save_item(
    conn: sqlite3.Connection,
    client: PlaidClient,
    public_token: str,
    institution_id: str | None,
    institution_name: str | None,
) -> int:
    external_id, access_token = client.exchange_public_token(public_token)
    keychain.set_access_token(external_id, access_token)
    with transaction(conn):
        row = conn.execute(
            """
            INSERT INTO items (external_id, institution_id, institution_name, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (provider, external_id) DO UPDATE SET status = 'active', last_error = NULL
            RETURNING id
            """,
            (external_id, institution_id, institution_name, utcnow()),
        ).fetchone()
    return row["id"]


def mark_reconnected(conn: sqlite3.Connection, item_id: int) -> None:
    with transaction(conn):
        updated = conn.execute(
            "UPDATE items SET status = 'active', last_error = NULL WHERE id = ?", (item_id,)
        ).rowcount
    if not updated:
        raise UnknownItem(item_id)
