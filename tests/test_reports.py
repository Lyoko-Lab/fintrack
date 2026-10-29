from __future__ import annotations

import sqlite3
from datetime import date

import pytest
from ledger_fakes import add_account, add_txn

from fintrack.edits import InvalidEdit, edit_transaction
from fintrack.enrich import enrich_all
from fintrack.reports import activity, overview, same_day_last_month

TODAY = date(2026, 10, 28)


@pytest.mark.parametrize(
    ("day", "expected"),
    [(date(2026, 10, 28), date(2026, 9, 28)), (date(2026, 3, 31), date(2026, 2, 28)), (date(2026, 1, 15), date(2025, 12, 15))],
)
def test_same_day_last_month_clamps_to_month_end(day, expected):
    assert same_day_last_month(day) == expected


@pytest.fixture
def ledger(db: sqlite3.Connection) -> sqlite3.Connection:
    checking = add_account(db, "Adv Plus Banking", "depository", mask="0001", current_cents=842137)
    card = add_account(db, "Sapphire Preferred", "credit", mask="4321", current_cents=184520, institution="Chase")
    # This month (through the 28th)
    add_txn(db, checking, 425000, "2026-10-15", "ACME CORP DES:PAYROLL")
    add_txn(db, card, -8612, "2026-10-25", "WHOLE FOODS MARKET", pfc="FOOD_AND_DRINK_GROCERIES")
    add_txn(db, card, 2599, "2026-10-26", "AMAZON MKTPL*REFUND", pfc="GENERAL_MERCHANDISE_ONLINE_MARKETPLACES")
    add_txn(db, card, -2350, "2026-10-28", "SHELL OIL", pfc="TRANSPORTATION_GAS", pending=True)
    add_txn(db, checking, -184520, "2026-10-20", "CHASE CREDIT CRD DES:AUTOPAY")  # transfer: not spending
    add_txn(db, card, 184520, "2026-10-21", "AUTOMATIC PAYMENT - THANK YOU")
    # Same period last month, and a day after it that must not count
    add_txn(db, checking, 410000, "2026-09-15", "ACME CORP DES:PAYROLL")
    add_txn(db, card, -5000, "2026-09-28", "BLUE BOTTLE COFFEE", pfc="FOOD_AND_DRINK_COFFEE")
    add_txn(db, card, -9900, "2026-09-29", "UNITED AIRLINES", pfc="TRAVEL_FLIGHTS")
    enrich_all(db)
    return db


def test_overview_counts_income_and_spending_but_not_transfers(ledger: sqlite3.Connection):
    result = overview(ledger, TODAY)

    assert result["period"] == {"start": "2026-10-01", "end": "2026-10-28"}
    assert result["previous_period"] == {"start": "2026-09-01", "end": "2026-09-28"}
    assert result["income"] == {"current": 425000, "previous": 410000}
    # 86.12 groceries + 23.50 gas (pending counts) − 25.99 refund; the card payment is a transfer.
    assert result["spending"] == {"current": 8612 + 2350 - 2599, "previous": 5000}


def test_net_cash_position_is_walked_back_through_posted_transactions(ledger: sqlite3.Connection):
    net = overview(ledger, TODAY)["net_cash"]

    assert (net["cash"], net["debt"], net["current"]) == (842137, 184520, 842137 - 184520)
    # Posted after Sep 28: payroll, groceries, refund, the payment pair (cancels out) and the Sep 29 flight.
    # The pending gas purchase isn't in any balance yet, so it doesn't move the past position either.
    posted_since = 425000 - 8612 + 2599 - 9900
    assert net["previous"] == net["current"] - posted_since


def test_activity_pages_newest_first_and_filters(ledger: sqlite3.Connection):
    first = activity(ledger, limit=3)
    assert [row["transaction_date"] for row in first["items"]] == ["2026-10-28", "2026-10-26", "2026-10-25"]
    second = activity(ledger, limit=3, before=(first["next"]["before"], first["next"]["before_id"]))
    assert second["items"][0]["transaction_date"] == "2026-10-21"

    assert [row["display_name"] for row in activity(ledger, query="whole")["items"]] == ["WHOLE FOODS MARKET"]
    assert {row["flow_type"] for row in activity(ledger, flow_type="transfer")["items"]} == {"transfer"}
    assert len(activity(ledger, flow_type="transfer")["items"]) == 2
    assert {row["category_id"] for row in activity(ledger, category_id="transport")["items"]} == {"transport.gas"}


def test_search_treats_percent_and_underscore_literally(ledger: sqlite3.Connection):
    assert activity(ledger, query="%")["items"] == []
    assert activity(ledger, query="_")["items"] == []


def test_edits_win_over_enrichment_and_can_be_reverted(ledger: sqlite3.Connection):
    coffee = activity(ledger, query="blue bottle")["items"][0]

    edit_transaction(ledger, coffee["id"], {"category_id": "dining.other", "note": " with the team "})
    enrich_all(ledger)  # a later sync must not undo the edit
    edited = activity(ledger, query="blue bottle")["items"][0]
    assert (edited["category_id"], edited["category_edited"], edited["note"]) == ("dining.other", 1, "with the team")

    edit_transaction(ledger, coffee["id"], {"category_id": None, "note": ""})
    reverted = activity(ledger, query="blue bottle")["items"][0]
    assert (reverted["category_id"], reverted["category_edited"], reverted["note"]) == ("dining.coffee", 0, None)
    assert ledger.execute("SELECT COUNT(*) FROM transaction_overrides").fetchone()[0] == 0


def test_only_leaf_categories_can_be_assigned(ledger: sqlite3.Connection):
    coffee = activity(ledger, query="blue bottle")["items"][0]
    with pytest.raises(InvalidEdit):
        edit_transaction(ledger, coffee["id"], {"category_id": "dining"})
    with pytest.raises(InvalidEdit):
        edit_transaction(ledger, coffee["id"], {"category_id": "no.such.category"})
