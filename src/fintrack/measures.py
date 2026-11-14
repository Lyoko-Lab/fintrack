"""The ledger's two basic quantities, defined once: every page that shows them asks here.

Flows are income and spending per day. They go by transaction_date (when it happened, not when it
posted), count pending transactions, and leave transfers out; a refund (a positive amount in a
spending category) comes off spending.

Positions are what the accounts hold at the end of a day: cash in the deposit accounts, debt on
the credit cards (what they owe, as a positive number), and net cash position, cash less debt.
Balances only exist for now, so an earlier day's position is today's less whatever posted since.
That goes by posted_date and posted transactions only, as a balance moves when a transaction
posts; a transfer between two connected accounts cancels out of the net.

Accounts the user left out of totals (account_settings) count in neither.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class Flow:
    income: int = 0
    spending: int = 0

    @property
    def net(self) -> int:
        return self.income - self.spending

    def __add__(self, other: Flow) -> Flow:
        return Flow(self.income + other.income, self.spending + other.spending)


@dataclass(frozen=True)
class Position:
    day: date
    cash: int
    debt: int

    @property
    def net(self) -> int:
        return self.cash - self.debt


def daily_flows(conn: sqlite3.Connection, start: date, end: date) -> dict[date, Flow]:
    """Income and spending on each day from start to end that has any."""
    rows = conn.execute(
        """
        SELECT transaction_date,
               COALESCE(SUM(CASE WHEN flow_type = 'income' THEN amount_cents END), 0),
               COALESCE(-SUM(CASE WHEN flow_type = 'expense' THEN amount_cents END), 0)
        FROM v_ledger
        WHERE transaction_date BETWEEN ? AND ? AND account_excluded = 0
        GROUP BY transaction_date
        """,
        (start.isoformat(), end.isoformat()),
    )
    return {date.fromisoformat(day): Flow(income, spending) for day, income, spending in rows}


def total_flow(conn: sqlite3.Connection, start: date, end: date) -> Flow:
    return sum(daily_flows(conn, start, end).values(), Flow())


def balances(conn: sqlite3.Connection) -> tuple[int, int, str | None]:
    """Cash, debt and when the bank last reported them."""
    cash, debt, as_of = conn.execute(
        """
        SELECT COALESCE(SUM(CASE WHEN type = 'depository' THEN current_cents END), 0),
               COALESCE(SUM(CASE WHEN type = 'credit' THEN current_cents END), 0),
               MAX(balance_as_of)
        FROM v_accounts
        WHERE excluded = 0
        """
    ).fetchone()
    return cash, debt, as_of


def positions(conn: sqlite3.Connection, start: date, today: date) -> list[Position]:
    """The position at the end of each day from start to today, today's being the current balances."""
    cash, debt, _ = balances(conn)
    moved = {
        date.fromisoformat(day): (cash_in, card_in)
        for day, cash_in, card_in in conn.execute(
            """
            SELECT t.posted_date,
                   SUM(CASE WHEN a.type = 'depository' THEN t.amount_cents ELSE 0 END),
                   SUM(CASE WHEN a.type = 'credit' THEN t.amount_cents ELSE 0 END)
            FROM transactions t JOIN v_accounts a ON a.id = t.account_id
            WHERE t.removed_at IS NULL AND t.pending = 0 AND a.type IN ('depository', 'credit') AND a.excluded = 0
              AND t.posted_date > ?
            GROUP BY t.posted_date
            """,
            (start.isoformat(),),
        )
    }
    result = []
    day = today
    while day >= start:
        result.append(Position(day, cash, debt))
        # Undo the day's postings: money into a card (a payment, a refund) had lowered what it owes.
        cash_in, card_in = moved.get(day, (0, 0))
        cash, debt = cash - cash_in, debt + card_in
        day -= timedelta(days=1)
    result.reverse()
    return result
