from __future__ import annotations

import sqlite3
from datetime import date

from ledger_fakes import add_account, add_txn

from fintrack.enrich import enrich_all
from fintrack.measures import Flow, daily_flows, positions

TODAY = date(2026, 11, 14)


def test_flows_count_pending_leave_transfers_out_and_take_refunds_off_spending(db: sqlite3.Connection):
    checking = add_account(db, "Checking", "depository", current_cents=100_000)
    card = add_account(db, "Card", "credit", current_cents=5_000)
    add_txn(db, checking, 300_000, "2026-11-13", "ACME CORP DES:PAYROLL ID:000123 PPD")
    add_txn(db, card, -6_000, "2026-11-13", "WHOLE FOODS MARKET", pfc="FOOD_AND_DRINK_GROCERIES", pending=True)
    add_txn(db, card, 1_000, "2026-11-13", "WHOLE FOODS MARKET REFUND", pfc="FOOD_AND_DRINK_GROCERIES")
    add_txn(db, checking, -50_000, "2026-11-13", "CHASE CREDIT CRD DES:AUTOPAY")  # a card payment: a transfer
    enrich_all(db)

    assert daily_flows(db, date(2026, 11, 1), TODAY) == {date(2026, 11, 13): Flow(income=300_000, spending=5_000)}


def test_positions_walk_back_through_posted_transactions(db: sqlite3.Connection):
    checking = add_account(db, "Checking", "depository", current_cents=100_000)
    card = add_account(db, "Card", "credit", current_cents=20_000)  # owed
    add_txn(db, card, -8_000, "2026-11-13", "UNITED AIRLINES")
    add_txn(db, checking, -5_000, "2026-11-14", "CHASE CREDIT CRD DES:AUTOPAY")
    add_txn(db, card, 5_000, "2026-11-14", "AUTOMATIC PAYMENT - THANK YOU")
    add_txn(db, card, -999, "2026-11-14", "BLUE BOTTLE COFFEE", pending=True)  # not in the balance yet

    result = positions(db, date(2026, 11, 12), TODAY)

    assert [(p.day.isoformat(), p.cash, p.debt, p.net) for p in result] == [
        ("2026-11-12", 105_000, 17_000, 88_000),
        ("2026-11-13", 105_000, 25_000, 80_000),  # the flight added to what the card owes
        ("2026-11-14", 100_000, 20_000, 80_000),  # paying the card moved cash, not net cash position
    ]
