"""Cash flow forecast: where net cash position, and the cash in the bank, are headed over the next two months.

Today's balances are carried forward day by day with what the last six months show:

- Recurring transactions: the same merchant or description, the same direction, a steady rhythm
  (weekly, every two weeks, twice a month or monthly), and still going. Payroll, rent and
  subscriptions land on their next expected dates at their recent typical amount.
- Everyday spending: the rest of what counts as spending, at the median weekly rate of the last
  13 weeks (so a one-off like a flight doesn't inflate it), spread evenly over the days and split
  between the accounts the way it has been.
- Card payments, as on the payment calendar: what is left of each card's statement is paid in full
  on its due date, and the next statement (the charges in between) a month later. They move money from the bank to a card, so they change
  the cash in the bank but not net cash position, which already subtracts what the cards owe.

Income that doesn't recur, like a tax refund or a bonus, isn't projected, so the forecast leans low.
The past part of the chart is the positions of measures.py, as on the Overview.
"""

from __future__ import annotations

import re
import sqlite3
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from .measures import balances, positions
from .reports import card_payments

HISTORY_DAYS = 60
HORIZON_DAYS = 60
LOOKBACK_DAYS = 180  # where recurring transactions are looked for
BASELINE_WEEKS = 13  # where the everyday spending rate comes from
STEADY = 0.75  # the share of gaps that must fit the rhythm
# How late an expected transaction can be before the series counts as stopped.
GRACE = {"weekly": 2, "biweekly": 3, "semimonthly": 3, "monthly": 5}
GRACE_DAYS = 25  # from a card statement to its due date, when the bank doesn't say


@dataclass
class Recurring:
    name: str
    direction: str  # "in" or "out"
    cadence: str  # weekly, biweekly, semimonthly or monthly
    amount: int  # signed cents, the typical recent amount
    account_id: int
    account_name: str
    account_type: str
    last: date
    days: tuple[int, ...] = ()  # days of the month, for semimonthly and monthly

    def after(self, day: date) -> date:
        """When this is next expected after `day`."""
        if self.cadence == "weekly":
            return day + timedelta(days=7)
        if self.cadence == "biweekly":
            return day + timedelta(days=14)
        # Twice a month or monthly: the listed day of the month nearest to where the rhythm points.
        # (Rent paid on the 31st for the 1st is followed by the 1st of the month after, not the next day.)
        step, shortest = (30, 20) if self.cadence == "monthly" else (15, 8)
        target = day + timedelta(days=step)
        candidates = [_on_day(_add_months(target, k), d) for k in (-1, 0, 1) for d in self.days]
        return min((c for c in candidates if (c - day).days >= shortest), key=lambda c: abs((c - target).days))


def _add_months(day: date, months: int) -> date:
    """The first of the month `months` after `day`'s month."""
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def _on_day(month: date, day: int) -> date:
    """That day of `month`, or its last day in a shorter month."""
    last = (_add_months(month, 1) - timedelta(days=1)).day
    return month.replace(day=min(day, last))


def _series_key(name: str) -> str:
    """Descriptions of the same payee differ in dates and reference numbers: keep the first few words."""
    words = [word for word in re.split(r"[^a-z]+", name.lower()) if word and not re.search(r"\d", word)]
    return " ".join(words[:3])


def _cadence(dates: list[date]) -> tuple[str, tuple[int, ...]] | None:
    gaps = [(later - earlier).days for earlier, later in zip(dates, dates[1:])]
    if not gaps:
        return None
    median = statistics.median(gaps)

    def steady(low: int, high: int) -> bool:
        return sum(low <= gap <= high for gap in gaps) >= STEADY * len(gaps)

    if 6 <= median <= 8 and len(dates) >= 4 and steady(5, 9):
        return "weekly", ()
    if 12 <= median <= 18 and len(dates) >= 4 and steady(11, 19):
        recent = dates[-6:]
        if steady(13, 15) and len({d.weekday() for d in recent}) == 1:
            return "biweekly", ()  # every other Friday
        # Twice a month: one day mid-month, the other at the turn of the month. A payday on the 1st
        # that falls on a weekend comes on the 30th, so the turn is the 1st or the last day by majority.
        middle = [d.day for d in recent if 8 <= d.day <= 23]
        turn = [d.day for d in recent if not 8 <= d.day <= 23]
        if middle and turn:
            turn_day = 1 if sum(day <= 7 for day in turn) * 2 >= len(turn) else 31
            return "semimonthly", tuple(sorted((round(statistics.median(middle)), turn_day)))
        return None
    if 26 <= median <= 35 and len(dates) >= 3 and steady(25, 36):
        return "monthly", (round(statistics.median(d.day for d in dates[-3:])),)
    return None


def find_recurring(rows: list[sqlite3.Row], today: date) -> tuple[list[Recurring], set[int]]:
    """The recurring series still going, and the ids of every transaction that belongs to one."""
    groups: dict[tuple[str, bool], list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        groups[(_series_key(row["display_name"] or ""), row["amount_cents"] > 0)].append(row)

    found: list[Recurring] = []
    members: set[int] = set()
    for (key, money_in), group in groups.items():
        if not key:
            continue
        by_day: dict[date, int] = defaultdict(int)
        for row in group:
            by_day[date.fromisoformat(row["transaction_date"])] += row["amount_cents"]
        dates = sorted(by_day)
        cadence = _cadence(dates)
        if cadence is None:
            continue
        last = max(group, key=lambda row: (row["transaction_date"], row["id"]))
        series = Recurring(
            name=last["display_name"],
            direction="in" if money_in else "out",
            cadence=cadence[0],
            days=cadence[1],
            amount=round(statistics.median(by_day[d] for d in dates[-3:])),
            account_id=last["account_id"],
            account_name=last["account_name"],
            account_type=last["account_type"],
            last=dates[-1],
        )
        if series.after(series.last) < today - timedelta(days=GRACE[series.cadence]):
            continue  # it has stopped
        found.append(series)
        members.update(row["id"] for row in group)
    return found, members


def _upcoming(series: Recurring, today: date, end: date) -> list[date]:
    dates = []
    expected = series.after(series.last)
    while expected <= end:
        # One that is a few days late is still expected: tomorrow.
        dates.append(expected if expected > today else today + timedelta(days=1))
        expected = series.after(expected)
    return dates


@dataclass
class _Card:
    account_id: int
    name: str
    debt: float
    unbilled: float = 0.0  # charged since the last statement
    closes: date | None = None  # the next statement date
    statement_day: int = 0
    days_to_pay: int = GRACE_DAYS  # from statement to due date
    payments: dict[date, float] = field(default_factory=dict)

    def pay(self, day: date, amount: float) -> None:
        self.payments[day] = self.payments.get(day, 0.0) + amount


def _cards(conn: sqlite3.Connection, today: date) -> tuple[dict[int, _Card], int]:
    """Each card's debt and the payments already known; the number of cards without a due date.

    The payments are the payment calendar's: what is left of the statement, paid in full on the due
    date. A bank that leaves out the statement's amount gets the card's whole balance paid instead,
    and one that leaves out the statement's date has it put a usual grace period before the due date.
    """
    statements = {payment["account_id"]: payment for payment in card_payments(conn, today)}
    cards: dict[int, _Card] = {}
    unknown = 0
    for account in conn.execute("SELECT id, name, mask, current_cents FROM v_accounts WHERE type = 'credit' AND excluded = 0"):
        name = f"{account['name']} ··{account['mask']}" if account["mask"] else account["name"]
        card = cards[account["id"]] = _Card(account["id"], name, float(account["current_cents"] or 0))
        statement = statements.get(account["id"])
        if statement is None or not statement["due_date"]:
            unknown += 1
            continue
        due = date.fromisoformat(statement["due_date"])
        owed = 0.0
        if statement["state"] != "paid":
            owed = card.debt if statement["remaining_cents"] is None else float(statement["remaining_cents"])
        if owed > 0:
            card.pay(max(due, today + timedelta(days=1)), owed)
        card.unbilled = max(card.debt - owed, 0.0)
        closed = due - timedelta(days=GRACE_DAYS)
        if statement["statement_date"]:
            closed = date.fromisoformat(statement["statement_date"])
        card.statement_day = closed.day
        card.days_to_pay = (due - closed).days
        card.closes = closed
        while card.closes <= today:
            card.closes = _on_day(_add_months(card.closes, 1), card.statement_day)
    return cards, unknown


def forecast(conn: sqlite3.Connection, today: date) -> dict[str, Any]:
    cash_today, _, as_of = balances(conn)
    past = positions(conn, today - timedelta(days=HISTORY_DAYS), today)
    history = [{"date": p.day.isoformat(), "net": p.net, "cash": p.cash} for p in past]

    # What recurs, and the everyday spending around it.
    rows = conn.execute(
        """
        SELECT id, account_id, account_name, account_type, amount_cents, transaction_date, display_name, flow_type
        FROM v_ledger
        WHERE account_type IN ('depository', 'credit') AND account_excluded = 0 AND transaction_date > ? AND transaction_date <= ?
          AND (flow_type IN ('income', 'expense')
               -- money moved to an account that isn't connected leaves the position too
               OR (flow_type = 'transfer' AND transfer_peer_id IS NULL AND category_id IS NOT 'transfer.card_payment'
                   AND account_type = 'depository'))
        ORDER BY transaction_date, id
        """,
        ((today - timedelta(days=LOOKBACK_DAYS)).isoformat(), today.isoformat()),
    ).fetchall()
    recurring, members = find_recurring(rows, today)
    baseline_start = today - timedelta(days=BASELINE_WEEKS * 7)
    weekly = [0] * BASELINE_WEEKS
    by_account: dict[int, int] = defaultdict(int)
    account_type: dict[int, str] = {}
    for row in rows:
        day = date.fromisoformat(row["transaction_date"])
        if row["flow_type"] != "expense" or row["id"] in members or day <= baseline_start:
            continue
        weekly[(today - day).days // 7] -= row["amount_cents"]
        by_account[row["account_id"]] -= row["amount_cents"]
        account_type[row["account_id"]] = row["account_type"]
    daily = max(statistics.median(weekly), 0) / 7
    spenders = {account: total for account, total in by_account.items() if total > 0}
    shares = {account: total / sum(spenders.values()) for account, total in spenders.items()}

    # The future, a day at a time.
    end = today + timedelta(days=HORIZON_DAYS)
    cards, cards_without_due_date = _cards(conn, today)
    planned: dict[date, list[Recurring]] = defaultdict(list)
    for series in recurring:
        for day in _upcoming(series, today, end):
            planned[day].append(series)
    events: list[dict[str, Any]] = []
    projection = []
    cash_left = float(cash_today)
    for offset in range(1, HORIZON_DAYS + 1):
        day = today + timedelta(days=offset)
        charged: dict[int, float] = defaultdict(float)  # by card
        for account, share in shares.items():
            if account_type[account] == "credit":
                charged[account] += daily * share
            else:
                cash_left -= daily * share
        for series in planned[day]:
            events.append(_event(day, "in" if series.amount > 0 else "out", series.name, series.amount, series.account_type))
            if series.account_type == "credit":
                charged[series.account_id] -= series.amount
            else:
                cash_left += series.amount
        for card in cards.values():
            card.debt += charged.get(card.account_id, 0.0)
            card.unbilled += charged.get(card.account_id, 0.0)
            if card.closes == day:
                if card.unbilled >= 1:
                    card.pay(day + timedelta(days=card.days_to_pay), card.unbilled)
                card.unbilled = 0.0
                card.closes = _on_day(_add_months(day, 1), card.statement_day)
            if (paid := card.payments.pop(day, None)) is not None:
                card.debt -= paid
                cash_left -= paid
                events.append(_event(day, "card", card.name, -round(paid), "depository"))
        debt = sum(card.debt for card in cards.values())
        projection.append({"date": day.isoformat(), "net": round(cash_left - debt), "cash": round(cash_left)})

    return {
        "today": today.isoformat(),
        "as_of": as_of,
        "history": history,
        "forecast": projection,
        "events": events,
        "recurring": [
            {
                "name": series.name,
                "direction": series.direction,
                "cadence": series.cadence,
                "amount": series.amount,
                "next_date": next(iter(_upcoming(series, today, end)), series.after(series.last)).isoformat(),
                "account_name": series.account_name,
                "account_type": series.account_type,
            }
            for series in sorted(recurring, key=lambda s: (s.direction != "in", -abs(s.amount)))
        ],
        "daily_spending": round(daily),
        "cards_without_due_date": cards_without_due_date,
    }


def _event(day: date, kind: str, name: str, amount: int, account_type: str) -> dict[str, Any]:
    return {"date": day.isoformat(), "kind": kind, "name": name, "amount": amount, "account_type": account_type}
