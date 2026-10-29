from __future__ import annotations

import sqlite3
from datetime import date

import pytest
from ledger_fakes import add_account, add_txn

from fintrack.enrich import enrich_all
from fintrack.insights import breakdown, comparison_spans, focus_span, period_start, shift, trend

TODAY = date(2026, 10, 28)  # a Wednesday


@pytest.mark.parametrize(
    ("granularity", "start"),
    [("day", date(2026, 10, 28)), ("week", date(2026, 10, 26)), ("month", date(2026, 10, 1)), ("year", date(2026, 1, 1))],
)
def test_period_start(granularity: str, start: date):
    assert period_start(TODAY, granularity) == start


def test_shift_crosses_year_boundaries():
    assert shift(date(2026, 1, 1), "month", -1) == date(2025, 12, 1)
    assert shift(date(2025, 12, 1), "month", 2) == date(2026, 2, 1)
    assert shift(date(2026, 10, 26), "week", -1) == date(2026, 10, 19)


def compared(granularity: str, start: date, comparison: str, today: date = TODAY) -> list[tuple[str, str]]:
    focus = focus_span(start, granularity, today)
    return [(s.start.isoformat(), s.end.isoformat()) for s in comparison_spans(focus, granularity, comparison)]


def test_a_running_period_is_compared_with_the_same_stretch():
    assert compared("month", date(2026, 10, 1), "previous") == [("2026-09-01", "2026-09-28")]
    assert compared("month", date(2026, 3, 1), "previous", today=date(2026, 3, 30)) == [("2026-02-01", "2026-02-28")]
    assert compared("week", date(2026, 10, 26), "previous") == [("2026-10-19", "2026-10-21")]
    assert compared("year", date(2026, 1, 1), "previous") == [("2025-01-01", "2025-10-28")]
    assert compared("month", date(2026, 10, 1), "year") == [("2025-10-01", "2025-10-28")]
    assert compared("day", date(2028, 2, 29), "year", today=date(2028, 2, 29)) == [("2027-02-28", "2027-02-28")]
    assert compared("month", date(2026, 10, 1), "average") == [
        ("2026-09-01", "2026-09-28"),
        ("2026-08-01", "2026-08-28"),
        ("2026-07-01", "2026-07-28"),
    ]


def test_a_finished_period_is_compared_in_full():
    assert compared("month", date(2026, 9, 1), "previous") == [("2026-08-01", "2026-08-31")]
    assert compared("month", date(2026, 3, 1), "previous", today=date(2026, 3, 31)) == [("2026-02-01", "2026-02-28")]
    assert compared("year", date(2024, 1, 1), "year") == [("2023-01-01", "2023-12-31")]


@pytest.fixture
def ledger(db: sqlite3.Connection) -> sqlite3.Connection:
    checking = add_account(db, "Checking", "depository")
    card = add_account(db, "Card", "credit", institution="Chase")
    add_txn(db, checking, 400000, "2026-09-15", "ACME DES:PAYROLL")
    add_txn(db, checking, 400000, "2026-10-15", "ACME DES:PAYROLL")
    add_txn(db, card, -5000, "2026-09-10", "BLUE BOTTLE", pfc="FOOD_AND_DRINK_COFFEE")
    add_txn(db, card, -9000, "2026-09-29", "UNITED AIRLINES", pfc="TRAVEL_FLIGHTS")  # past Sept 28
    add_txn(db, card, -12000, "2026-10-10", "NOPA", pfc="FOOD_AND_DRINK_RESTAURANT")
    add_txn(db, card, -3000, "2026-10-12", "BLUE BOTTLE", pfc="FOOD_AND_DRINK_COFFEE")
    add_txn(db, card, -20000, "2026-10-20", "WHOLE FOODS", pfc="FOOD_AND_DRINK_GROCERIES")
    add_txn(db, card, 2000, "2026-10-21", "WHOLE FOODS REFUND", pfc="FOOD_AND_DRINK_GROCERIES")  # reduces spending
    add_txn(db, checking, -50000, "2026-10-22", "CHASE CREDIT CRD DES:AUTOPAY")  # a transfer: in neither total
    enrich_all(db)
    return db


def test_trend_starts_at_the_first_transaction(ledger: sqlite3.Connection):
    periods = trend(ledger, "month", TODAY)["periods"]
    assert [(p["start"], p["end"], p["complete"], p["income"], p["spending"], p["net"]) for p in periods] == [
        ("2026-09-01", "2026-09-30", True, 400000, 14000, 386000),
        ("2026-10-01", "2026-10-28", False, 400000, 33000, 367000),
    ]


def test_breakdown_against_the_same_stretch_of_last_month(ledger: sqlite3.Connection):
    result = breakdown(ledger, "month", TODAY, "previous", TODAY)
    assert result["period"] == {"start": "2026-10-01", "end": "2026-10-28", "complete": False}
    assert result["comparison_periods"] == [{"start": "2026-09-01", "end": "2026-09-28"}]
    assert result["totals"] == {
        "current": {"income": 400000, "spending": 33000, "net": 367000},
        "comparison": {"income": 400000, "spending": 5000, "net": 395000},
    }
    assert [(g["id"], g["current"], g["comparison"]) for g in result["spending"]] == [
        ("groceries", 18000, 0),
        ("dining", 15000, 5000),
    ]
    assert result["spending"][0]["children"] == []  # a category with no subcategories
    assert [(c["id"], c["current"], c["comparison"]) for c in result["spending"][1]["children"]] == [
        ("dining.restaurants", 12000, 0),
        ("dining.coffee", 3000, 5000),
    ]
    assert [(g["id"], g["current"], g["comparison"]) for g in result["income"]] == [("income", 400000, 400000)]
    # Over the past year: dining 200 (coffee 50 + 120 + 30), groceries 180 (200 - a 20 refund), travel 90.
    assert result["featured"] == ["dining", "groceries", "travel"]


def test_the_featured_groups_do_not_depend_on_the_period_shown(ledger: sqlite3.Connection):
    october = breakdown(ledger, "month", TODAY, "previous", TODAY)
    september = breakdown(ledger, "month", date(2026, 9, 1), "year", TODAY)
    assert october["featured"] == september["featured"]


def test_breakdown_of_a_finished_month_and_of_an_average(ledger: sqlite3.Connection):
    september = breakdown(ledger, "month", date(2026, 9, 12), "previous", TODAY)
    assert september["period"] == {"start": "2026-09-01", "end": "2026-09-30", "complete": True}
    assert september["totals"]["current"]["spending"] == 14000

    averaged = breakdown(ledger, "month", TODAY, "average", TODAY)["totals"]["comparison"]
    assert averaged == {"income": 133333, "spending": 1667, "net": 131666}  # September's stretch over three months
