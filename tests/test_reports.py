from __future__ import annotations

import sqlite3
from datetime import date

import pytest
from ledger_fakes import add_account, add_txn

from fintrack.edits import InvalidEdit, edit_transaction
from fintrack.enrich import enrich_all
from fintrack.reports import activity, card_payments, overview, same_day_last_month

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
    september = activity(ledger, date_from=date(2026, 9, 1), date_to=date(2026, 9, 28))["items"]
    assert [row["transaction_date"] for row in september] == ["2026-09-28", "2026-09-15"]


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


def add_statement(db: sqlite3.Connection, account_id: int, *, owed: int | None, due: str | None, statement_date: str = "2026-10-03",
                  minimum: int | None = 3500, last_payment: tuple[int, str] | None = None, overdue: bool | None = None) -> None:  # fmt: skip
    db.execute(
        """
        INSERT INTO card_statements (account_id, statement_date, statement_cents, minimum_cents, due_date,
                                     last_payment_cents, last_payment_date, is_overdue, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, '2026-10-28T00:00:00Z')
        """,
        (account_id, statement_date, owed, minimum, due, *(last_payment or (None, None)), overdue),
    )


def test_card_payments_say_what_is_left_to_pay_most_urgent_first(db: sqlite3.Connection):
    checking = add_account(db, "Checking", "depository")
    paid_in_ledger, partly_paid, paid_per_bank, late, unknown = (
        add_account(db, name, "credit", institution=bank)
        for name, bank in [("Paid in ledger", "Chase"), ("Partly paid", "Chase"), ("Paid per bank", "BOA"),
                           ("Late", "Amex"), ("Unknown", "Amex")]
    )  # fmt: skip
    add_statement(db, paid_in_ledger, owed=50000, due="2026-11-02")
    add_txn(db, checking, -50000, "2026-10-20", "CHASE CREDIT CRD DES:AUTOPAY")
    add_txn(db, paid_in_ledger, 50000, "2026-10-21", "AUTOMATIC PAYMENT - THANK YOU")
    add_statement(db, partly_paid, owed=80000, due="2026-11-15")
    add_txn(db, partly_paid, 30000, "2026-10-12", "AUTOMATIC PAYMENT - THANK YOU")
    add_txn(db, partly_paid, 99999, "2026-09-30", "AUTOMATIC PAYMENT - THANK YOU")  # before the statement: doesn't count
    add_statement(db, paid_per_bank, owed=20000, due="2026-11-05", last_payment=(20000, "2026-10-09"))
    add_statement(db, late, owed=12000, due="2026-10-25")
    add_statement(db, unknown, owed=None, minimum=None, due=None)
    enrich_all(db)

    payments = card_payments(db, TODAY)
    assert [p["account_name"] for p in payments] == ["Late", "Partly paid", "Unknown", "Paid in ledger", "Paid per bank"]
    by_name = {p["account_name"]: p for p in payments}
    assert (by_name["Late"]["state"], by_name["Late"]["days_left"]) == ("overdue", -3)
    partly = by_name["Partly paid"]
    assert (partly["state"], partly["paid_cents"], partly["remaining_cents"], partly["days_left"]) == ("due", 30000, 50000, 18)
    assert (by_name["Paid in ledger"]["state"], by_name["Paid in ledger"]["remaining_cents"]) == ("paid", 0)
    assert by_name["Paid per bank"]["state"] == "paid"
    unknown_card = by_name["Unknown"]
    assert (unknown_card["state"], unknown_card["remaining_cents"], unknown_card["days_left"]) == ("due", None, None)
