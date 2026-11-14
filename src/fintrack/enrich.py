"""Enrichment: give every transaction a category, which also decides income / expense / transfer.

Runs after every sync, rule change and edit, and rewrites transaction_enrichment from
scratch, so changes apply to history too. The user's own edits live in
transaction_overrides and always win (see v_ledger).

The user's rules (rules.py) come first. Without one, the automatic rules, first match wins:
  1. Not a cash account (loans, investments)     → transfer: outside income and spending
  2. Person-to-person apps (Zelle, Venmo, ...)   → in: AA / reimbursement, which offsets spending
                                                   out: personal transfer, counted as spending
  3. Credit card payments, seen from either side → transfer
  4. Payroll, tax refund, interest deposits      → income
  5. Plaid's category, checked against the direction the money moved
  6. Fallback by direction
Then equal-and-opposite amounts between the user's own accounts are paired into transfers.
Pairing never re-labels what the user decided (a rule or an edit), but a transfer the
user decided can still claim its other half.
"""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from . import rules as user_rules
from .db import transaction

CASH_ACCOUNT_TYPES = ("depository", "credit")
PAIR_WINDOW_DAYS = 5

P2P = re.compile(r"\b(zelle|venmo|paypal|cash ?app|square cash|apple cash)\b", re.I)
# How a credit card describes a payment it received ("AUTOMATIC PAYMENT - THANK YOU").
CARD_PAYMENT_RECEIVED = re.compile(
    r"payment.{0,3}thank you|thank you.{0,3}payment|auto ?pay|automatic payment|online payment"
    r"|mobile payment|payment received|e-?payment|payment from chk",
    re.I,
)
# How a bank account describes paying a credit card ("CHASE CREDIT CRD DES:AUTOPAY").
CARD_PAYMENT_SENT = re.compile(
    r"credit crd|card ?member ?serv|credit card bill pay|applecard"
    r"|(payment|pmt|pymt|auto ?pay|e-?pay).{0,25}\b(crd|credit card)\b"
    r"|\b(crd|credit card)\b.{0,25}\b(payment|pmt|pymt|auto ?pay|e-?pay)"
    r"|(american express|amex).{0,25}(pmt|payment|e-?pay)"
    r"|(citi|discover|capital one|barclaycard|chase card).{0,25}(pmt|payment|e-?pay|auto ?pay)",
    re.I,
)
INCOME_DEPOSITS = (
    (re.compile(r"payroll|payrl|dir(ect)? ?dep|salary", re.I), "income.salary", "payroll"),
    (re.compile(r"irs treas|tax ref", re.I), "income.tax_refund", "tax_refund"),
    (re.compile(r"interest (earned|paid|payment)", re.I), "income.interest", "interest"),
)
# Weaker evidence that a transaction moves money between accounts; used only for pairing.
TRANSFER_HINT = re.compile(r"transfer|xfer|trnsfr|payment|pmt|pymt|auto ?pay|e-?pay|online banking", re.I)

# Plaid personal_finance_category (detailed) prefix → category. First match wins, so
# specific prefixes come before their catch-alls. Covers both PFC v1 and v2 names.
PFC_CATEGORIES = (
    ("FOOD_AND_DRINK_GROCERIES", "groceries"),
    ("FOOD_AND_DRINK_COFFEE", "dining.coffee"),
    ("FOOD_AND_DRINK_FAST_FOOD", "dining.fast_food"),
    ("FOOD_AND_DRINK_RESTAURANT", "dining.restaurants"),
    ("FOOD_AND_DRINK_BEER_WINE_AND_LIQUOR", "dining.bars"),
    ("FOOD_AND_DRINK", "dining.other"),
    ("GENERAL_MERCHANDISE_ONLINE_MARKETPLACES", "shopping.online"),
    ("GENERAL_MERCHANDISE_CLOTHING", "shopping.clothing"),
    ("GENERAL_MERCHANDISE_ELECTRONICS", "shopping.electronics"),
    ("GENERAL_MERCHANDISE_SUPERSTORES", "shopping.general"),
    ("GENERAL_MERCHANDISE_DEPARTMENT_STORES", "shopping.general"),
    ("GENERAL_MERCHANDISE_DISCOUNT_STORES", "shopping.general"),
    ("GENERAL_MERCHANDISE_CONVENIENCE_STORES", "shopping.general"),
    ("GENERAL_MERCHANDISE_GIFTS", "gifts"),
    ("GENERAL_MERCHANDISE", "shopping.other"),
    ("TRANSPORTATION_TAXIS", "transport.rideshare"),
    ("TRANSPORTATION_GAS", "transport.gas"),
    ("TRANSPORTATION_PARKING", "transport.parking"),
    ("TRANSPORTATION_TOLLS", "transport.parking"),
    ("TRANSPORTATION", "transport.transit"),
    ("GENERAL_SERVICES_AUTOMOTIVE", "transport.auto"),
    ("TRAVEL_FLIGHTS", "travel.flights"),
    ("TRAVEL_LODGING", "travel.lodging"),
    ("TRAVEL", "travel.other"),
    ("RENT_AND_UTILITIES_RENT", "housing.rent"),
    ("RENT_AND_UTILITIES_INTERNET", "bills.telecom"),
    ("RENT_AND_UTILITIES_TELEPHONE", "bills.telecom"),
    ("RENT_AND_UTILITIES", "bills.utilities"),
    ("HOME_IMPROVEMENT", "housing.home"),
    ("MEDICAL", "health.medical"),
    ("PERSONAL_CARE_GYMS", "health.fitness"),
    ("PERSONAL_CARE", "personal.care"),
    ("GENERAL_SERVICES_EDUCATION", "personal.education"),
    ("GENERAL_SERVICES_INSURANCE", "bills.insurance"),
    ("GENERAL_SERVICES", "personal.services"),
    ("ENTERTAINMENT", "entertainment"),
    ("GOVERNMENT_AND_NON_PROFIT_DONATIONS", "gifts"),
    ("GOVERNMENT_AND_NON_PROFIT", "taxes"),
    ("BANK_FEES_INTEREST", "fees.interest"),
    ("BANK_FEES", "fees.bank"),
    ("INCOME_WAGES", "income.salary"),
    ("INCOME_SALARY", "income.salary"),
    ("INCOME_INTEREST", "income.interest"),
    ("INCOME_TAX_REFUND", "income.tax_refund"),
    ("INCOME", "income.other"),
    # Repayments are spending when the purchase itself was financed by a lender we don't
    # track (home, car, tuition, buy-now-pay-later); otherwise they just move borrowed money.
    ("LOAN_PAYMENTS_CREDIT_CARD", "transfer.card_payment"),
    ("LOAN_PAYMENTS_MORTGAGE", "housing.mortgage"),
    ("LOAN_PAYMENTS_CAR", "transport.auto"),
    ("LOAN_PAYMENTS_STUDENT", "personal.education"),
    ("LOAN_PAYMENTS_BNPL", "shopping.other"),
    ("LOAN_PAYMENTS", "transfer.loan"),
    ("LOAN_DISBURSEMENTS", "transfer.loan"),
    ("TRANSFER_IN_CASH_ADVANCES", "transfer.loan"),
    ("TRANSFER_IN_DEPOSIT", "income.other"),
    ("TRANSFER_OUT_WITHDRAWAL", "other.cash"),
    ("TRANSFER_IN", "transfer.internal"),
    ("TRANSFER_OUT", "transfer.internal"),
)


@dataclass(frozen=True)
class Txn:
    id: int
    account_id: int
    account_type: str
    amount_cents: int
    posted_date: str
    text: str  # bank's original description plus Plaid's cleaned name
    merchant_name: str | None
    pfc_detailed: str | None


@dataclass
class Decision:
    category_id: str
    rule: str
    transfer_peer_id: int | None = None
    user_rule_id: int | None = None  # set when rule == "user_rule"


def pfc_category(pfc_detailed: str | None) -> str | None:
    if not pfc_detailed:
        return None
    return next((category for prefix, category in PFC_CATEGORIES if pfc_detailed.startswith(prefix)), None)


def classify(txn: Txn, kinds: dict[str, str]) -> Decision:
    inflow = txn.amount_cents > 0
    if txn.account_type not in CASH_ACCOUNT_TYPES:
        return Decision("transfer.loan" if txn.account_type == "loan" else "transfer.other", "account")
    # PayPal also processes ordinary purchases; those carry the real merchant's name.
    if P2P.search(txn.text) and (txn.merchant_name is None or P2P.search(txn.merchant_name)):
        return Decision("other.reimbursement" if inflow else "other.p2p", "p2p")
    if txn.account_type == "credit" and inflow and CARD_PAYMENT_RECEIVED.search(txn.text):
        return Decision("transfer.card_payment", "card_payment")
    if txn.account_type == "depository" and not inflow and CARD_PAYMENT_SENT.search(txn.text):
        return Decision("transfer.card_payment", "card_payment")
    if txn.account_type == "depository" and inflow:
        for pattern, category, rule in INCOME_DEPOSITS:
            if pattern.search(txn.text):
                return Decision(category, rule)

    category = pfc_category(txn.pfc_detailed)
    if category is None:
        if inflow:
            return Decision("income.other" if txn.account_type == "depository" else "other.credits", "fallback")
        return Decision("other.uncategorized", "fallback")
    if kinds[category] == "income" and (not inflow or txn.account_type == "credit"):
        # Money leaving can't be income, and money landing on a card is a refund or credit, not pay.
        return Decision("other.credits" if inflow else "other.uncategorized", "direction")
    return Decision(category, "pfc")


def pair_transfers(
    txns: list[Txn],
    decisions: dict[int, Decision],
    kinds: dict[str, str],
    settled: Mapping[int, str] | None = None,
) -> None:
    """Link a money-out and an equal money-in on two of the user's accounts within a few days.

    At least one side must already look like a transfer and both must show some sign of
    being one, so an unrelated refund of the same amount isn't swept in. `settled` maps
    transactions whose category the user decided to that category: they pair only when the
    user made them a transfer, and keep their category when they do.
    """
    settled = settled or {}

    def strong(t: Txn) -> bool:
        return kinds[settled.get(t.id, decisions[t.id].category_id)] == "transfer"

    def plausible(t: Txn) -> bool:
        if t.id in settled:
            return strong(t)
        return (
            strong(t)
            or bool(TRANSFER_HINT.search(t.text))
            or (t.pfc_detailed or "").startswith(("TRANSFER", "LOAN_PAYMENTS"))
            or (t.account_type == "credit" and t.amount_cents > 0)  # money landing on a card is usually a payment
        )

    cash = [t for t in txns if t.account_type in CASH_ACCOUNT_TYPES and plausible(t)]
    inflows_by_amount: dict[int, list[Txn]] = defaultdict(list)
    for t in cash:
        if t.amount_cents > 0:
            inflows_by_amount[t.amount_cents].append(t)

    matched: set[int] = set()
    for out in sorted((t for t in cash if t.amount_cents < 0), key=lambda t: (t.posted_date, t.id)):
        day = date.fromisoformat(out.posted_date).toordinal()
        best: tuple[tuple[bool, int, int], Txn] | None = None
        for inc in inflows_by_amount.get(-out.amount_cents, ()):
            if inc.id in matched or inc.account_id == out.account_id or not (strong(out) or strong(inc)):
                continue
            gap = abs(date.fromisoformat(inc.posted_date).toordinal() - day)
            if gap > PAIR_WINDOW_DAYS:
                continue
            key = (not strong(inc), gap, inc.id)  # prefer a counterpart that is itself clearly a transfer
            if best is None or key < best[0]:
                best = (key, inc)
        if best is None:
            continue
        inc = best[1]
        matched.add(inc.id)
        category = "transfer.card_payment" if inc.account_type == "credit" else "transfer.internal"
        for side, peer in ((out, inc), (inc, out)):
            if side.id in settled:
                decisions[side.id].transfer_peer_id = peer.id
            else:
                decisions[side.id] = Decision(category, "pair", peer.id)


# A pending transaction is replaced by a new posted one; keep whatever the user set on it.
_CARRY_OVER_EDITS = """
INSERT INTO transaction_overrides (transaction_id, category_id, note, updated_at)
SELECT posted.id, o.category_id, o.note, o.updated_at
FROM transactions posted
JOIN transactions pending ON pending.external_id = posted.pending_external_id
JOIN transaction_overrides o ON o.transaction_id = pending.id
WHERE posted.removed_at IS NULL
ON CONFLICT (transaction_id) DO NOTHING
"""

# A bank can also withdraw a transaction and send it again under a new id. Its edits move to the
# replacement: a live transaction on the same account with the same amount and payee, dated within
# three days, that first arrived within a week of the withdrawal and has no edits of its own. They
# move rather than copy, so a second look-alike never picks them up too.
_WITHDRAWN_WITH_EDITS = """
SELECT gone.id, gone.account_id, gone.amount_cents, gone.transaction_date, gone.removed_at,
       COALESCE(gone.merchant_name, gone.description, gone.original_description) AS payee
FROM transaction_overrides o
JOIN transactions gone ON gone.id = o.transaction_id
WHERE gone.removed_at IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM transactions posted WHERE posted.pending_external_id = gone.external_id)
"""
_REPLACEMENT = """
SELECT t.id FROM transactions t
WHERE t.removed_at IS NULL AND t.account_id = :account_id AND t.amount_cents = :amount_cents
  AND COALESCE(t.merchant_name, t.description, t.original_description) = :payee
  AND abs(julianday(t.transaction_date) - julianday(:transaction_date)) <= 3
  AND julianday(t.first_seen_at) BETWEEN julianday(:removed_at) - 1 AND julianday(:removed_at) + 7
  AND NOT EXISTS (SELECT 1 FROM transaction_overrides edited WHERE edited.transaction_id = t.id)
ORDER BY abs(julianday(t.transaction_date) - julianday(:transaction_date)), t.id
LIMIT 1
"""


def _carry_over_edits(conn: sqlite3.Connection) -> None:
    conn.execute(_CARRY_OVER_EDITS)
    for gone in conn.execute(_WITHDRAWN_WITH_EDITS).fetchall():
        replacement = conn.execute(_REPLACEMENT, dict(gone)).fetchone()
        if replacement is not None:
            conn.execute("UPDATE transaction_overrides SET transaction_id = ? WHERE transaction_id = ?", (replacement["id"], gone["id"]))


def enrich_all(conn: sqlite3.Connection) -> int:
    """Re-derive the category of every live transaction. Returns how many were classified."""
    with transaction(conn):
        _carry_over_edits(conn)
        kinds = {row["id"]: row["kind"] for row in conn.execute("SELECT id, kind FROM categories")}
        txns = [
            Txn(*row)
            for row in conn.execute(
                f"""
                SELECT t.id, t.account_id, a.type, t.amount_cents, t.posted_date, {user_rules.MATCH_TEXT},
                       t.merchant_name, t.pfc_detailed
                FROM transactions t JOIN accounts a ON a.id = t.account_id
                WHERE t.removed_at IS NULL
                """
            )
        ]
        rules = user_rules.load_rules(conn)
        decisions: dict[int, Decision] = {}
        settled: dict[int, str] = {}  # what the user decided: by a rule, or (stronger) by editing the transaction
        for t in txns:
            if rule := user_rules.first_match(rules, t.merchant_name, t.text, t.amount_cents):
                decisions[t.id] = Decision(rule.category_id, "user_rule", user_rule_id=rule.id)
                settled[t.id] = rule.category_id
            else:
                decisions[t.id] = classify(t, kinds)
        settled |= {
            row["transaction_id"]: row["category_id"]
            for row in conn.execute("SELECT transaction_id, category_id FROM transaction_overrides WHERE category_id IS NOT NULL")
        }
        pair_transfers(txns, decisions, kinds, settled)
        conn.execute("DELETE FROM transaction_enrichment")
        conn.executemany(
            """
            INSERT INTO transaction_enrichment (transaction_id, category_id, rule, transfer_peer_id, user_rule_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            [(tid, d.category_id, d.rule, d.transfer_peer_id, d.user_rule_id) for tid, d in decisions.items()],
        )
    return len(decisions)
