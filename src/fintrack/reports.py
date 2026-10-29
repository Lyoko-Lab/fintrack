"""Read models for the UI: Overview metrics, the Activity feed, and the category list.

Everything reads v_ledger, so the numbers here are the same ones Ask will see later.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Any


def same_day_last_month(day: date) -> date:
    last_of_previous = day.replace(day=1) - timedelta(days=1)
    return last_of_previous.replace(day=min(day.day, last_of_previous.day))


def _income_and_spending(conn: sqlite3.Connection, start: date, end: date) -> tuple[int, int]:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(CASE WHEN flow_type = 'income' THEN amount_cents END), 0),
               COALESCE(-SUM(CASE WHEN flow_type = 'expense' THEN amount_cents END), 0)
        FROM v_ledger
        WHERE transaction_date BETWEEN ? AND ?
        """,
        (start.isoformat(), end.isoformat()),
    ).fetchone()
    return row[0], row[1]


def overview(conn: sqlite3.Connection, today: date) -> dict[str, Any]:
    """Month-to-date income and spending, and net cash position, each against the same point last month."""
    start = today.replace(day=1)
    previous_end = same_day_last_month(today)
    previous_start = previous_end.replace(day=1)
    income, spending = _income_and_spending(conn, start, today)
    previous_income, previous_spending = _income_and_spending(conn, previous_start, previous_end)

    cash, debt, as_of = conn.execute(
        """
        SELECT COALESCE(SUM(CASE WHEN type = 'depository' THEN current_cents END), 0),
               COALESCE(SUM(CASE WHEN type = 'credit' THEN current_cents END), 0),
               MAX(balance_as_of)
        FROM accounts
        """
    ).fetchone()
    # Balances only exist for "now", but every posted transaction moved one of them, so the
    # position at an earlier date is today's minus whatever posted since. Transfers between
    # two tracked accounts cancel out, as they should.
    posted_since = conn.execute(
        """
        SELECT COALESCE(SUM(t.amount_cents), 0)
        FROM transactions t JOIN accounts a ON a.id = t.account_id
        WHERE t.removed_at IS NULL AND t.pending = 0 AND a.type IN ('depository', 'credit') AND t.posted_date > ?
        """,
        (previous_end.isoformat(),),
    ).fetchone()[0]

    return {
        "today": today.isoformat(),
        "period": {"start": start.isoformat(), "end": today.isoformat()},
        "previous_period": {"start": previous_start.isoformat(), "end": previous_end.isoformat()},
        "income": {"current": income, "previous": previous_income},
        "spending": {"current": spending, "previous": previous_spending},
        "net_cash": {
            "current": cash - debt,
            "previous": cash - debt - posted_since,
            "cash": cash,
            "debt": debt,
            "as_of": as_of,
        },
    }


def activity(
    conn: sqlite3.Connection,
    *,
    limit: int = 50,
    before: tuple[str, int] | None = None,
    query: str | None = None,
    account_id: int | None = None,
    category_id: str | None = None,
    flow_type: str | None = None,
) -> dict[str, Any]:
    """One page of the unified feed, newest first. `before` is the (date, id) cursor from the previous page."""
    clauses: list[str] = []
    params: list[Any] = []
    if before is not None:
        clauses.append("(transaction_date < ? OR (transaction_date = ? AND id < ?))")
        params += [before[0], before[0], before[1]]
    if query:
        pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        clauses.append(
            "(display_name LIKE ? ESCAPE '\\' OR original_description LIKE ? ESCAPE '\\' OR note LIKE ? ESCAPE '\\')"
        )
        params += [pattern] * 3
    if account_id is not None:
        clauses.append("account_id = ?")
        params.append(account_id)
    if category_id:
        clauses.append("(category_id = ? OR category_id IN (SELECT id FROM categories WHERE parent_id = ?))")
        params += [category_id, category_id]
    if flow_type:
        clauses.append("flow_type = ?")
        params.append(flow_type)

    rows = conn.execute(
        f"SELECT * FROM v_ledger WHERE {' AND '.join(clauses) or '1'} ORDER BY transaction_date DESC, id DESC LIMIT ?",
        (*params, limit + 1),
    ).fetchall()
    items = [dict(row) for row in rows[:limit]]
    more = len(rows) > limit
    return {"items": items, "next": {"before": items[-1]["transaction_date"], "before_id": items[-1]["id"]} if more else None}


def categories(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT c.id, c.parent_id, c.name, c.kind,
               NOT EXISTS (SELECT 1 FROM categories k WHERE k.parent_id = c.id) AS assignable
        FROM categories c ORDER BY c.position
        """
    ).fetchall()
    return [dict(row) for row in rows]


def ledger_row(conn: sqlite3.Connection, transaction_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM v_ledger WHERE id = ?", (transaction_id,)).fetchone()
    return dict(row) if row else None
