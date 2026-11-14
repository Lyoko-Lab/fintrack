from __future__ import annotations

import sqlite3

import pytest
from ledger_fakes import add_account, add_txn

from fintrack.enrich import PFC_CATEGORIES, Decision, Txn, classify, enrich_all, pair_transfers


@pytest.fixture
def kinds(db: sqlite3.Connection) -> dict[str, str]:
    return {row["id"]: row["kind"] for row in db.execute("SELECT id, kind FROM categories")}


def txn(amount_cents: int, text: str, *, account_type: str = "depository", pfc: str | None = None,
        merchant: str | None = None, account_id: int = 1, day: str = "2026-10-20", id: int = 1) -> Txn:  # fmt: skip
    return Txn(id, account_id, account_type, amount_cents, day, text, merchant, pfc)


def category(t: Txn, kinds: dict[str, str]) -> str:
    return classify(t, kinds).category_id


def test_category_names_are_stored_in_english(db: sqlite3.Connection):
    names = [row["name"] for row in db.execute("SELECT name FROM categories")]
    assert len(names) == 61 and all(name.isascii() for name in names)  # the web app translates them by id


def test_every_mapped_category_exists_and_is_assignable(db: sqlite3.Connection):
    leaves = {row["id"] for row in db.execute("SELECT id FROM categories c WHERE NOT EXISTS (SELECT 1 FROM categories k WHERE k.parent_id = c.id)")}
    assert {target for _, target in PFC_CATEGORIES} <= leaves


@pytest.mark.parametrize(
    ("amount", "text", "account_type", "pfc", "merchant", "expected"),
    [
        # Payroll that Plaid mistook for a restaurant (seen in Plaid Sandbox).
        (81000, "Sweetgreen inc payroll ppd id", "depository", "FOOD_AND_DRINK_RESTAURANT", "Sweetgreen", "income.salary"),
        (425000, "ACME CORP DES:PAYROLL ID:XXXXX INDN:JANE DOE CO ID:XXXXX PPD", "depository", None, None, "income.salary"),
        # A card payment that Plaid labelled salary (seen in Plaid Sandbox).
        (283580, "Payment Thank You-Mobile", "credit", "INCOME_SALARY", None, "transfer.card_payment"),
        (184520, "AUTOMATIC PAYMENT - THANK YOU", "credit", None, None, "transfer.card_payment"),
        (-184520, "CHASE CREDIT CRD DES:AUTOPAY ID:XXXXX INDN:JANE DOE CO ID:XXXXX PPD", "depository", None, None, "transfer.card_payment"),
        (-64018, "AMERICAN EXPRESS DES:ACH PMT ID:XXXXX INDN:JANE DOE CO ID:XXXXX CCD", "depository", None, None, "transfer.card_payment"),
        (-31240, "Online Banking payment to CRD 7781 Confirmation# XXXXX", "depository", None, None, "transfer.card_payment"),
        # Debit card purchases that only look like card payments.
        (-1547, "DBT CRD 199371271 02/13 FWLE9M PANERA BREAD 44 MASON OH 078", "depository", "FOOD_AND_DRINK_RESTAURANT", "Panera Bread", "dining.restaurants"),
        (-4825, "CREDIT CARD PURCHASE SMART AND FINAL #1 ANAHEIM CA CARD 5", "depository", "FOOD_AND_DRINK_GROCERIES", "Smart & Final", "groceries"),
        (-18600, "PURCHASE AUTHORIZED ON 02/04 AMERICAN AIRLINES QA WORTH GA CARD 84", "depository", "TRAVEL_FLIGHTS", "American Airlines", "travel.flights"),
        # Person-to-person apps: money back from friends offsets spending; money sent counts as spending.
        (4500, "Zelle payment from JANE DOE Conf# abc123", "depository", "TRANSFER_IN_ACCOUNT_TRANSFER", None, "other.reimbursement"),
        (-12000, "Zelle payment to JOHN DOE Conf# def456", "depository", "TRANSFER_OUT_ACCOUNT_TRANSFER", None, "other.p2p"),
        (-14509, "ADDFUNDS VENMO 5193501845284 INTERNET PAYMENT", "depository", "TRANSFER_OUT_TRANSFER_OUT_FROM_APPS", None, "other.p2p"),
        # A purchase paid through PayPal stays with the merchant.
        (-10344, "ACH PAYMENT PAYPAL INST XFER DUNKIN' 1498570029012 IN", "depository", "FOOD_AND_DRINK_COFFEE", "Dunkin'", "dining.coffee"),
        # Refunds and statement credits on a card reduce spending; they are never income.
        (2599, "AMAZON MKTPL*REFUND", "credit", "GENERAL_MERCHANDISE_ONLINE_MARKETPLACES", "Amazon", "shopping.online"),
        (1500, "PLATINUM UBER CASH CREDIT", "credit", "INCOME_OTHER_INCOME", None, "other.credits"),
        (-2134, "INTEREST CHARGE ON PURCHASES", "credit", "BANK_FEES_INTEREST_CHARGE", None, "fees.interest"),
        (12, "Interest payment", "depository", "INCOME_INTEREST_EARNED", None, "income.interest"),
        # Borrowed money is not income.
        (9500, "Brigit XX/XX #406735377 PMNT RCVD Brigit New York NY", "depository", "LOAN_DISBURSEMENTS_CASH_ADVANCES", "Brigit", "transfer.loan"),
        (5000, "MORTGAGE PAYMENT RECEIVED", "loan", "LOAN_PAYMENTS_MORTGAGE_PAYMENT", None, "transfer.loan"),
        (30000, "MOBILE DEPOSIT", "depository", None, None, "income.other"),
        (-999, "SQ *SOMEWHERE", "depository", None, None, "other.uncategorized"),
    ],
)
def test_classification(kinds, amount, text, account_type, pfc, merchant, expected):
    assert category(txn(amount, text, account_type=account_type, pfc=pfc, merchant=merchant), kinds) == expected


def run_pairing(txns: list[Txn], kinds: dict[str, str]) -> dict[int, Decision]:
    decisions = {t.id: classify(t, kinds) for t in txns}
    pair_transfers(txns, decisions, kinds)
    return decisions


def test_a_card_payment_is_paired_with_the_card_receiving_it(kinds):
    paid = txn(-184520, "CHASE CREDIT CRD DES:AUTOPAY", day="2026-10-20", account_id=1, id=1)
    received = txn(184520, "AUTOMATIC PAYMENT - THANK YOU", account_type="credit", day="2026-10-21", account_id=2, id=2)

    decisions = run_pairing([paid, received], kinds)

    assert decisions[1] == Decision("transfer.card_payment", "pair", 2)
    assert decisions[2] == Decision("transfer.card_payment", "pair", 1)


def test_pairing_prefers_the_payment_over_a_same_amount_refund(kinds):
    paid = txn(-5000, "AMERICAN EXPRESS DES:ACH PMT", day="2026-10-20", account_id=1, id=1)
    refund = txn(5000, "AMAZON MKTPL*REFUND", account_type="credit", pfc="GENERAL_MERCHANDISE_ONLINE_MARKETPLACES",
                 day="2026-10-20", account_id=2, id=2)  # fmt: skip
    received = txn(5000, "ONLINE PAYMENT - THANK YOU", account_type="credit", day="2026-10-22", account_id=2, id=3)

    decisions = run_pairing([paid, refund, received], kinds)

    assert decisions[1].transfer_peer_id == 3
    assert decisions[2].category_id == "shopping.online"


def test_transfers_more_than_five_days_apart_are_not_paired(kinds):
    paid = txn(-5000, "CHASE CREDIT CRD DES:AUTOPAY", day="2026-10-01", account_id=1, id=1)
    received = txn(5000, "AUTOMATIC PAYMENT - THANK YOU", account_type="credit", day="2026-10-09", account_id=2, id=2)

    decisions = run_pairing([paid, received], kinds)

    assert decisions[1].transfer_peer_id is None and decisions[2].transfer_peer_id is None
    assert decisions[1].category_id == decisions[2].category_id == "transfer.card_payment"


def test_matching_amounts_without_any_transfer_sign_stay_separate(kinds):
    purchase = txn(-4200, "WHOLE FOODS MARKET", pfc="FOOD_AND_DRINK_GROCERIES", account_id=1, id=1)
    deposit = txn(4200, "MOBILE DEPOSIT", account_id=2, id=2)

    decisions = run_pairing([purchase, deposit], kinds)

    assert decisions[1].category_id == "groceries"
    assert decisions[2].category_id == "income.other"


def test_enrich_all_classifies_and_keeps_edits_when_a_pending_transaction_posts(db: sqlite3.Connection):
    checking = add_account(db, "Adv Plus Banking", "depository", mask="0001")
    card = add_account(db, "Sapphire Preferred", "credit", mask="4321", institution="Chase")
    add_txn(db, checking, -184520, "2026-10-20", "CHASE CREDIT CRD DES:AUTOPAY")
    add_txn(db, card, 184520, "2026-10-21", "AUTOMATIC PAYMENT - THANK YOU")
    pending = add_txn(db, card, -575, "2026-10-26", "BLUE BOTTLE COFFEE", pfc="FOOD_AND_DRINK_COFFEE",
                      pending=True, external_id="p1")  # fmt: skip
    db.execute("INSERT INTO transaction_overrides VALUES (?, 'dining.other', 'team coffee', '2026-10-26T00:00:00Z')", (pending,))
    db.execute("UPDATE transactions SET removed_at = '2026-10-28T00:00:00Z' WHERE id = ?", (pending,))
    posted = add_txn(db, card, -575, "2026-10-26", "BLUE BOTTLE COFFEE", pfc="FOOD_AND_DRINK_COFFEE",
                     posted="2026-10-28", pending_external_id="p1")  # fmt: skip

    assert enrich_all(db) == 3

    ledger = {row["id"]: row for row in db.execute("SELECT * FROM v_ledger")}
    assert {row["flow_type"] for row in ledger.values() if row["id"] != posted} == {"transfer"}
    assert ledger[posted]["category_id"] == "dining.other"
    assert ledger[posted]["category_edited"] == 1
    assert ledger[posted]["note"] == "team coffee"
    paid = next(row for row in ledger.values() if row["amount_cents"] == -184520)
    assert (paid["peer_account_name"], paid["peer_account_mask"]) == ("Sapphire Preferred", "4321")


def test_edits_follow_a_transaction_the_bank_sends_again_under_a_new_id(db: sqlite3.Connection):
    card = add_account(db, "Sapphire Preferred", "credit")
    first = add_txn(db, card, -575, "2026-11-10", "BLUE BOTTLE COFFEE", pfc="FOOD_AND_DRINK_COFFEE")
    twin = add_txn(db, card, -575, "2026-11-10", "BLUE BOTTLE COFFEE", pfc="FOOD_AND_DRINK_COFFEE")  # a second cup
    db.execute("INSERT INTO transaction_overrides VALUES (?, 'dining.other', 'team coffee', '2026-11-10T09:00:00Z')", (first,))
    # The bank withdraws the first and sends it again, a day later and under a new id, in the next sync.
    db.execute("UPDATE transactions SET removed_at = '2026-11-12T06:00:00Z' WHERE id = ?", (first,))
    again = add_txn(db, card, -575, "2026-11-11", "BLUE BOTTLE COFFEE", pfc="FOOD_AND_DRINK_COFFEE")
    db.execute("UPDATE transactions SET first_seen_at = '2026-11-12T06:00:00Z' WHERE id = ?", (again,))
    unrelated = add_txn(db, card, -575, "2026-11-11", "STARBUCKS", pfc="FOOD_AND_DRINK_COFFEE")
    db.execute("UPDATE transactions SET first_seen_at = '2026-11-12T06:00:00Z' WHERE id = ?", (unrelated,))

    enrich_all(db)
    enrich_all(db)  # and again: the edits don't spread to look-alikes

    ledger = {row["id"]: row for row in db.execute("SELECT id, category_id, note FROM v_ledger")}
    assert (ledger[again]["category_id"], ledger[again]["note"]) == ("dining.other", "team coffee")
    assert (ledger[twin]["category_id"], ledger[twin]["note"]) == ("dining.coffee", None)
    assert (ledger[unrelated]["category_id"], ledger[unrelated]["note"]) == ("dining.coffee", None)
