"""The user's categorization rules: "transactions that look like this go in that category".

A rule outranks the automatic rules in enrich.py, and an edit to a single transaction
outranks the rule. After any change the caller re-runs enrich_all, so a new rule also
re-files past transactions.

Matching ignores case and runs of spaces:
  merchant     the merchant name Plaid recognized, compared whole ("Starbucks")
  description  a keyword found anywhere in the bank's description or Plaid's name for it
A rule can be limited to money coming in or going out. When several rules match, the
most specific wins: merchant rules before keywords, longer keywords before shorter,
one-way rules before two-way ones, newer before older.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from .db import transaction, utcnow
from .reports import is_assignable

MATCH_FIELDS = ("merchant", "description")
DIRECTIONS = ("inflow", "outflow")
EDITABLE_FIELDS = ("pattern", "direction", "category_id")
MAX_PATTERN_LENGTH = 100

# What a description keyword is matched against: the bank's description plus Plaid's name for it.
MATCH_TEXT = "COALESCE(t.original_description, '') || ' ' || COALESCE(t.description, '')"


class UnknownRule(LookupError):
    pass


class InvalidRule(ValueError):
    pass


def normalize(text: str | None) -> str:
    return " ".join((text or "").lower().split())


@dataclass(frozen=True)
class Rule:
    id: int
    match_field: str
    pattern: str
    direction: str | None
    category_id: str
    needle: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "needle", normalize(self.pattern))

    def matches(self, merchant: str, text: str, amount_cents: int) -> bool:
        """`merchant` and `text` must already be normalize()d."""
        if self.direction == "inflow" and amount_cents <= 0:
            return False
        if self.direction == "outflow" and amount_cents >= 0:
            return False
        return merchant == self.needle if self.match_field == "merchant" else self.needle in text


def load_rules(conn: sqlite3.Connection) -> list[Rule]:
    """Every rule, most specific first, so the first that matches a transaction decides it."""
    rows = conn.execute(
        """
        SELECT id, match_field, pattern, direction, category_id FROM category_rules
        ORDER BY match_field = 'description', length(pattern) DESC, direction IS NULL, id DESC
        """
    ).fetchall()
    return [Rule(*row) for row in rows]


def first_match(rules: list[Rule], merchant_name: str | None, text: str, amount_cents: int) -> Rule | None:
    merchant, text = normalize(merchant_name), normalize(text)
    return next((rule for rule in rules if rule.matches(merchant, text, amount_cents)), None)


def _condition(match_field: str, pattern: str, direction: str | None) -> tuple[str, str, str | None]:
    if match_field not in MATCH_FIELDS:
        raise InvalidRule(f"match_field must be one of {MATCH_FIELDS}")
    if direction is not None and direction not in DIRECTIONS:
        raise InvalidRule(f"direction must be one of {DIRECTIONS} or null")
    pattern = " ".join(pattern.split())
    if not pattern:
        raise InvalidRule("规则内容不能为空")
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise InvalidRule(f"规则内容不能超过 {MAX_PATTERN_LENGTH} 个字符")
    return match_field, pattern, direction


def _check_category(conn: sqlite3.Connection, category_id: str) -> None:
    if not is_assignable(conn, category_id):
        raise InvalidRule(f"{category_id!r} 不是可以直接使用的分类")


def _same_condition(conn: sqlite3.Connection, match_field: str, pattern: str, direction: str | None) -> int | None:
    row = conn.execute(
        "SELECT id FROM category_rules WHERE match_field = ? AND lower(pattern) = lower(?) AND direction IS ?",
        (match_field, pattern, direction),
    ).fetchone()
    return row["id"] if row else None


def save_rule(conn: sqlite3.Connection, match_field: str, pattern: str, direction: str | None, category_id: str) -> int:
    """Create a rule, or re-point the existing rule with the same condition. Returns its id."""
    match_field, pattern, direction = _condition(match_field, pattern, direction)
    _check_category(conn, category_id)
    now = utcnow()
    with transaction(conn):
        if (rule_id := _same_condition(conn, match_field, pattern, direction)) is not None:
            conn.execute(
                "UPDATE category_rules SET pattern = ?, category_id = ?, updated_at = ? WHERE id = ?",
                (pattern, category_id, now, rule_id),
            )
            return rule_id
        return conn.execute(
            """
            INSERT INTO category_rules (match_field, pattern, direction, category_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?) RETURNING id
            """,
            (match_field, pattern, direction, category_id, now, now),
        ).fetchone()["id"]


def update_rule(conn: sqlite3.Connection, rule_id: int, changes: dict[str, Any]) -> None:
    """Change a rule's keyword, direction or category. A direction of None means either way."""
    if unknown := set(changes) - set(EDITABLE_FIELDS):
        raise InvalidRule(f"cannot edit {sorted(unknown)}")
    with transaction(conn):
        current = conn.execute("SELECT * FROM category_rules WHERE id = ?", (rule_id,)).fetchone()
        if current is None:
            raise UnknownRule(rule_id)
        merged = {name: current[name] for name in EDITABLE_FIELDS} | changes
        if merged["category_id"] is None:
            raise InvalidRule("规则必须有分类")
        _, pattern, direction = _condition(current["match_field"], merged["pattern"] or "", merged["direction"])
        _check_category(conn, merged["category_id"])
        if _same_condition(conn, current["match_field"], pattern, direction) not in (None, rule_id):
            raise InvalidRule("已经有一条条件相同的规则")
        conn.execute(
            "UPDATE category_rules SET pattern = ?, direction = ?, category_id = ?, updated_at = ? WHERE id = ?",
            (pattern, direction, merged["category_id"], utcnow(), rule_id),
        )


def delete_rule(conn: sqlite3.Connection, rule_id: int) -> None:
    with transaction(conn):
        if conn.execute("DELETE FROM category_rules WHERE id = ?", (rule_id,)).rowcount == 0:
            raise UnknownRule(rule_id)


def list_rules(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Rules, most recently changed first, each with how many transactions it currently decides."""
    rows = conn.execute(
        """
        SELECT r.id, r.match_field, r.pattern, r.direction, r.category_id, r.created_at, r.updated_at,
               c.name AS category_name, c.kind AS flow_type,
               (SELECT COUNT(*) FROM transaction_enrichment e JOIN transactions t ON t.id = e.transaction_id
                WHERE e.user_rule_id = r.id AND t.removed_at IS NULL) AS transaction_count
        FROM category_rules r JOIN categories c ON c.id = r.category_id
        ORDER BY r.updated_at DESC, r.id DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def count_matches(conn: sqlite3.Connection, match_field: str, pattern: str, direction: str | None) -> int:
    """How many live transactions a rule with this condition would match, ignoring other rules."""
    rule = Rule(0, *_condition(match_field, pattern, direction), category_id="")
    rows = conn.execute(
        f"SELECT t.merchant_name, {MATCH_TEXT}, t.amount_cents FROM transactions t WHERE t.removed_at IS NULL"
    )
    return sum(rule.matches(normalize(merchant), normalize(text), amount) for merchant, text, amount in rows)
