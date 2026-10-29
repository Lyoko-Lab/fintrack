"""The user's categorization rules, and how they rank against the automatic rules and edits."""

from __future__ import annotations

import sqlite3

import pytest
from ledger_fakes import add_account, add_txn

from fintrack.edits import edit_transaction
from fintrack.enrich import enrich_all
from fintrack.rules import InvalidRule, UnknownRule, count_matches, delete_rule, list_rules, save_rule, update_rule


def category_of(db: sqlite3.Connection, transaction_id: int) -> str:
    return db.execute("SELECT category_id FROM v_ledger WHERE id = ?", (transaction_id,)).fetchone()[0]


@pytest.fixture
def checking(db: sqlite3.Connection) -> int:
    return add_account(db, "Checking", "depository")


@pytest.fixture
def card(db: sqlite3.Connection) -> int:
    return add_account(db, "Card", "credit", institution="Chase")


def test_a_merchant_rule_re_files_past_and_future_transactions(db: sqlite3.Connection, card: int):
    old = add_txn(db, card, -650, "2025-03-02", "STARBUCKS STORE 123", merchant="Starbucks", pfc="FOOD_AND_DRINK_COFFEE")
    save_rule(db, "merchant", "starbucks", None, "dining.restaurants")  # matching ignores case
    new = add_txn(db, card, -720, "2026-10-20", "STARBUCKS STORE 456", merchant="Starbucks", pfc="FOOD_AND_DRINK_COFFEE")
    other = add_txn(db, card, -500, "2026-10-21", "BLUE BOTTLE", merchant="Blue Bottle Coffee", pfc="FOOD_AND_DRINK_COFFEE")
    enrich_all(db)

    assert [category_of(db, t) for t in (old, new, other)] == ["dining.restaurants", "dining.restaurants", "dining.coffee"]
    row = db.execute("SELECT category_rule, user_rule_field, user_rule_pattern FROM v_ledger WHERE id = ?", (old,)).fetchone()
    assert tuple(row) == ("user_rule", "merchant", "starbucks")


def test_a_keyword_rule_can_be_limited_to_one_direction(db: sqlite3.Connection, checking: int):
    paid_back = add_txn(db, checking, 4000, "2026-10-03", "Zelle payment from ALEX CHEN Conf# 1")
    sent = add_txn(db, checking, -4000, "2026-10-04", "Zelle payment to ALEX CHEN Conf# 2")
    save_rule(db, "description", "alex   chen", "inflow", "income.other")  # runs of spaces don't matter
    enrich_all(db)

    assert category_of(db, paid_back) == "income.other"
    assert category_of(db, sent) == "other.p2p"  # still the automatic rule


def test_the_most_specific_rule_wins_and_an_edit_beats_every_rule(db: sqlite3.Connection, card: int):
    uber_eats = add_txn(db, card, -2400, "2026-10-05", "UBER EATS 8005928996", merchant="Uber Eats", pfc="FOOD_AND_DRINK_RESTAURANT")
    uber = add_txn(db, card, -1800, "2026-10-06", "UBER TRIP", merchant="Uber", pfc="TRANSPORTATION_TAXIS_AND_RIDE_SHARES")
    save_rule(db, "description", "uber", None, "transport.rideshare")
    save_rule(db, "description", "uber eats", None, "dining.fast_food")  # a longer keyword is more specific
    save_rule(db, "merchant", "Uber", None, "transport.transit")  # merchant rules come before keywords
    enrich_all(db)
    assert category_of(db, uber_eats) == "dining.fast_food"
    assert category_of(db, uber) == "transport.transit"

    edit_transaction(db, uber, {"category_id": "travel.other"})
    enrich_all(db)
    assert category_of(db, uber) == "travel.other"


def test_saving_the_same_condition_again_re_points_the_rule(db: sqlite3.Connection):
    first = save_rule(db, "merchant", "Netflix", None, "entertainment")
    assert save_rule(db, "merchant", "NETFLIX", None, "bills.subscriptions") == first
    assert [(r["pattern"], r["category_id"]) for r in list_rules(db)] == [("NETFLIX", "bills.subscriptions")]
    assert save_rule(db, "merchant", "Netflix", "inflow", "other.credits") != first  # another direction, another rule


def test_deleting_a_rule_hands_its_transactions_back(db: sqlite3.Connection, card: int):
    netflix = add_txn(db, card, -1549, "2026-10-07", "NETFLIX.COM", merchant="Netflix", pfc="ENTERTAINMENT_TV_AND_MOVIES")
    rule = save_rule(db, "merchant", "Netflix", None, "bills.subscriptions")
    enrich_all(db)
    assert list_rules(db)[0]["transaction_count"] == 1

    delete_rule(db, rule)
    enrich_all(db)
    assert category_of(db, netflix) == "entertainment"
    with pytest.raises(UnknownRule):
        delete_rule(db, rule)


def test_updating_a_rule(db: sqlite3.Connection):
    rule = save_rule(db, "description", "payroll", "inflow", "income.salary")
    other = save_rule(db, "description", "bonus", "inflow", "income.other")
    update_rule(db, rule, {"direction": None, "category_id": "income.other"})
    assert {r["id"]: (r["direction"], r["category_id"]) for r in list_rules(db)}[rule] == (None, "income.other")

    with pytest.raises(InvalidRule):
        update_rule(db, other, {"pattern": "PAYROLL", "direction": None})  # the first rule's condition
    with pytest.raises(UnknownRule):
        update_rule(db, 999, {"category_id": "income.other"})


@pytest.mark.parametrize(
    ("match_field", "pattern", "direction", "category_id"),
    [
        ("merchant", "   ", None, "dining.coffee"),
        ("merchant", "x" * 101, None, "dining.coffee"),
        ("merchant", "Starbucks", None, "dining"),  # a group: only its categories can be given to a transaction
        ("merchant", "Starbucks", "sideways", "dining.coffee"),
        ("amount", "5", None, "dining.coffee"),
    ],
)
def test_invalid_rules_are_refused(db: sqlite3.Connection, match_field, pattern, direction, category_id):
    with pytest.raises(InvalidRule):
        save_rule(db, match_field, pattern, direction, category_id)


def test_a_transfer_rule_still_claims_its_other_half(db: sqlite3.Connection, checking: int):
    savings = add_account(db, "Savings", "depository", institution="Ally")
    out = add_txn(db, checking, -50000, "2026-10-10", "TO SAVINGS 4411")
    into = add_txn(db, savings, 50000, "2026-10-11", "Online Transfer from CHK 1234")
    enrich_all(db)
    assert category_of(db, into) == "income.other"  # neither side looked like a transfer on its own

    save_rule(db, "description", "to savings", "outflow", "transfer.internal")
    enrich_all(db)
    rows = {r["id"]: tuple(r)[1:] for r in db.execute("SELECT id, category_id, category_rule, transfer_peer_id FROM v_ledger")}
    assert rows[out] == ("transfer.internal", "user_rule", into)  # the rule's category stays
    assert rows[into] == ("transfer.internal", "pair", out)


def test_editing_one_half_of_a_transfer_into_spending_unpairs_it(db: sqlite3.Connection, checking: int, card: int):
    paid = add_txn(db, checking, -18452, "2026-10-20", "CHASE CREDIT CRD DES:AUTOPAY")
    received = add_txn(db, card, 18452, "2026-10-21", "AUTOMATIC PAYMENT - THANK YOU")
    enrich_all(db)
    assert db.execute("SELECT transfer_peer_id FROM v_ledger WHERE id = ?", (received,)).fetchone()[0] == paid

    edit_transaction(db, paid, {"category_id": "housing.rent"})
    enrich_all(db)
    assert db.execute("SELECT transfer_peer_id FROM v_ledger WHERE id = ?", (received,)).fetchone()[0] is None


def test_count_matches_previews_a_condition(db: sqlite3.Connection, card: int):
    for day in ("2026-10-01", "2026-10-08"):
        add_txn(db, card, -1549, day, "NETFLIX.COM", merchant="Netflix")
    add_txn(db, card, 1549, "2026-10-09", "NETFLIX.COM REFUND", merchant="Netflix")

    assert count_matches(db, "merchant", "netflix", None) == 3
    assert count_matches(db, "merchant", "netflix", "outflow") == 2
    assert count_matches(db, "description", "refund", None) == 1
