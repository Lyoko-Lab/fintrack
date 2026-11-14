from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Any

import pytest
from ledger_fakes import add_account, add_txn

from fintrack.enrich import enrich_all
from fintrack.forecast import Recurring, _cadence, find_recurring, forecast

TODAY = date(2026, 11, 14)  # a Saturday


def days(*isos: str) -> list[date]:
    return [date.fromisoformat(iso) for iso in isos]


def every(first: date, step: int, until: date = TODAY) -> list[date]:
    result = []
    while first <= until:
        result.append(first)
        first += timedelta(days=step)
    return result


@pytest.mark.parametrize(
    ("dates", "expected"),
    [
        (every(date(2026, 9, 5), 7), ("weekly", ())),
        (every(date(2026, 6, 5), 14), ("biweekly", ())),  # every other Friday
        # The 1st and the 15th, moved to the Friday before when they fall on a weekend.
        (days("2026-07-01", "2026-07-15", "2026-07-31", "2026-08-14", "2026-09-01", "2026-09-15", "2026-10-01",
              "2026-10-15", "2026-10-30", "2026-11-13"), ("semimonthly", (1, 15))),  # fmt: skip
        # Rent paid a day early once still reads as monthly, on the 1st.
        (days("2026-06-01", "2026-07-01", "2026-07-31", "2026-09-01", "2026-10-01", "2026-11-01"), ("monthly", (1,))),
        (days("2026-06-03", "2026-06-06", "2026-06-26", "2026-07-05", "2026-08-15", "2026-08-19"), None),
        (days("2026-10-01", "2026-11-01"), None),  # twice isn't a pattern yet
    ],
)
def test_rhythms(dates: list[date], expected: tuple[str, tuple[int, ...]] | None):
    assert _cadence(dates) == expected


def monthly_on(day: int, last: date) -> Recurring:
    return Recurring("Rent", "out", "monthly", -100, 1, "Checking", "depository", last, (day,))


def test_the_next_date_follows_the_rhythm_not_the_last_payment():
    assert monthly_on(1, date(2026, 11, 1)).after(date(2026, 11, 1)) == date(2026, 12, 1)
    # Paid early on Jan 31 for Feb 1: the next one is Mar 1, not the next day.
    assert monthly_on(1, date(2027, 1, 31)).after(date(2027, 1, 31)) == date(2027, 3, 1)
    # The 31st in a 30-day month falls on the 30th.
    assert monthly_on(31, date(2026, 10, 31)).after(date(2026, 10, 31)) == date(2026, 11, 30)


def rows(name: str, amount: int, dates: list[date], account_id: int = 1) -> list[dict[str, Any]]:
    return [
        {"id": n, "account_id": account_id, "account_name": "Checking", "account_type": "depository", "amount_cents": amount,
         "transaction_date": day.isoformat(), "display_name": f"{name} {day:%m%d} ID:{n:06d}", "flow_type": "expense"}
        for n, day in enumerate(dates, start=account_id * 1000)
    ]  # fmt: skip


def test_only_series_still_going_are_recurring():
    current = rows("OAK STREET APTS DES:RENT", -200_000, days("2026-08-01", "2026-09-01", "2026-10-01", "2026-11-01"))
    stopped = rows("OLD GYM CLUB", -5_000, days("2026-05-03", "2026-06-03", "2026-07-03", "2026-08-03"), account_id=2)
    found, members = find_recurring(current + stopped, TODAY)
    assert [(series.name.split(" ID")[0], series.cadence, series.amount) for series in found] == [
        ("OAK STREET APTS DES:RENT 1101", "monthly", -200_000)
    ]
    assert members == {row["id"] for row in current}


@pytest.fixture
def ledger(db: sqlite3.Connection) -> sqlite3.Connection:
    checking = add_account(db, "Everyday Checking", "depository", current_cents=500_000)
    card = add_account(db, "Rewards Card", "credit", mask="0202", current_cents=30_000)
    add_account(db, "Store Card", "credit", current_cents=0, institution="Chase")  # no statement
    for day in every(date(2026, 6, 12), 14):  # every other Friday, the last one yesterday
        add_txn(db, checking, 300_000, day.isoformat(), "ACME CORP DES:PAYROLL ID:000123 PPD")
    for month in range(6, 12):
        add_txn(db, checking, -200_000, f"2026-{month:02d}-01", "OAK STREET APTS DES:RENT", merchant="Oak Street Apartments")
    for day in every(TODAY - timedelta(days=120), 1):
        add_txn(db, card, -500, day.isoformat(), "BLUE BOTTLE COFFEE", merchant="Blue Bottle Coffee", pfc="FOOD_AND_DRINK_COFFEE")
    db.execute(
        """
        INSERT INTO card_statements (account_id, statement_date, statement_cents, minimum_cents, due_date, updated_at)
        VALUES (?, '2026-10-31', 20000, 2500, '2026-11-25', '2026-11-14T00:00:00Z')
        """,
        (card,),
    )
    enrich_all(db)
    return db


def test_the_forecast_carries_balances_forward(ledger: sqlite3.Connection):
    result = forecast(ledger, TODAY)
    point = {p["date"]: p for p in result["history"] + result["forecast"]}

    def change(day: str, field: str) -> int:
        before = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
        return point[day][field] - point[before][field]

    assert result["history"][-1] == {"date": "2026-11-14", "net": 470_000, "cash": 500_000}
    assert change("2026-11-13", "cash") == 300_000  # the past: payroll on the 13th
    assert [r["name"] for r in result["recurring"]] == ["ACME CORP DES:PAYROLL ID:000123 PPD", "Oak Street Apartments"]
    assert result["daily_spending"] == 500 and result["cards_without_due_date"] == 1

    assert point["2026-11-15"]["net"] == 469_500  # coffee on the card
    assert change("2026-11-27", "net") == 300_000 - 500  # the next payroll
    assert change("2026-12-01", "cash") == -200_000  # rent
    # The statement is paid on its due date: cash goes down, net cash position doesn't.
    assert change("2026-11-25", "cash") == -20_000 and change("2026-11-25", "net") == -500
    # The next statement closes on Nov 30 with what was charged since Oct 31 (100 + 16 days of coffee).
    assert {"date": "2026-12-25", "kind": "card", "name": "Rewards Card ··0202", "amount": -18_000,
            "account_type": "depository"} in result["events"]  # fmt: skip
    assert result["forecast"][-1]["date"] == "2027-01-13"


def test_cards_are_paid_on_their_due_dates_even_when_the_bank_leaves_details_out(db: sqlite3.Connection):
    add_account(db, "Everyday Checking", "depository", current_cents=500_000)
    freedom = add_account(db, "Freedom", "credit", mask="1111", current_cents=40_000)
    store = add_account(db, "Store Card", "credit", mask="2222", current_cents=8_000)
    db.executemany(
        """
        INSERT INTO card_statements (account_id, statement_date, statement_cents, due_date, updated_at)
        VALUES (?, NULL, ?, ?, '2026-11-14T00:00:00Z')
        """,
        [(freedom, 25_000, "2026-11-25"), (store, None, "2026-11-20")],  # no statement date; no amount either
    )

    result = forecast(db, TODAY)

    cards = [(e["date"], e["name"], e["amount"]) for e in result["events"] if e["kind"] == "card"]
    assert cards == [
        ("2026-11-20", "Store Card ··2222", -8_000),  # the whole balance, with no statement amount to go by
        ("2026-11-25", "Freedom ··1111", -25_000),  # as on the payment calendar
        # Its statement taken as closing 25 days before the due date: the next one, on the 30th,
        # bills the rest of the balance, due 25 days later.
        ("2026-12-25", "Freedom ··1111", -15_000),
    ]
    assert result["cards_without_due_date"] == 0
