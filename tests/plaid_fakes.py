"""A scripted stand-in for the Plaid API, served through an httpx2 MockTransport, plus payload builders."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx2

from fintrack.plaid import PlaidClient


@dataclass
class FakeItem:
    accounts: list[dict[str, Any]]
    pages: dict[str | None, dict[str, Any]] = field(default_factory=dict)  # cursor -> /transactions/sync body
    cards: list[dict[str, Any]] | None = None  # /liabilities/get credit entries; None: the bank has none


class FakePlaid:
    def __init__(self) -> None:
        self.items: dict[str, FakeItem] = {}  # keyed by access token
        self.next_exchange = ("item-1", "access-1")  # (item_id, access_token) for the next public token exchange
        self.failures: list[tuple[str, dict[str, Any], str]] = []
        self.requests: list[tuple[str, dict[str, Any]]] = []

    def client(self) -> PlaidClient:
        return PlaidClient("https://sandbox.plaid.com", "client-id", "secret", transport=httpx2.MockTransport(self._handle))

    def fail_next(self, path: str, error_code: str, **match: Any) -> None:
        """Fail the next request to `path` whose JSON body contains every key/value in `match`."""
        self.failures.append((path, match, error_code))

    def _handle(self, request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        body = json.loads(request.content or b"{}")
        self.requests.append((path, body))
        for i, (fail_path, match, error_code) in enumerate(self.failures):
            if fail_path == path and all(body.get(k) == v for k, v in match.items()):
                del self.failures[i]
                error = {"error_type": "ITEM_ERROR", "error_code": error_code, "error_message": "simulated", "request_id": "req"}
                return httpx2.Response(400, json=error)
        if path == "/link/token/create":
            return httpx2.Response(200, json={"link_token": "link-sandbox-token", "request_id": "req"})
        if path == "/item/public_token/exchange":
            item_id, access_token = self.next_exchange
            return httpx2.Response(200, json={"item_id": item_id, "access_token": access_token, "request_id": "req"})
        item = self.items[body["access_token"]]
        if path == "/accounts/get":
            return httpx2.Response(200, json={"accounts": item.accounts, "item": {}, "request_id": "req"})
        if path == "/transactions/sync":
            return httpx2.Response(200, json=item.pages[body.get("cursor")])
        if path == "/liabilities/get":
            if item.cards is None:
                error = {"error_type": "ITEM_ERROR", "error_code": "NO_LIABILITY_ACCOUNTS", "error_message": "none"}
                return httpx2.Response(400, json=error)
            liabilities = {"credit": item.cards, "mortgage": [], "student": []}
            return httpx2.Response(200, json={"accounts": item.accounts, "liabilities": liabilities, "request_id": "req"})
        return httpx2.Response(404, json={"error_code": "NOT_FOUND", "error_message": path})


def account(
    account_id: str,
    *,
    type: str = "credit",
    subtype: str = "credit card",
    current: float = 845.20,
    available: float | None = 4154.80,
    limit: float | None = 5000,
    name: str = "Sapphire Preferred",
    mask: str = "4321",
) -> dict[str, Any]:
    return {
        "account_id": account_id, "name": name, "official_name": None, "mask": mask, "type": type, "subtype": subtype,
        "balances": {"current": current, "available": available, "limit": limit,
                     "iso_currency_code": "USD", "unofficial_currency_code": None},
    }  # fmt: skip


def card(
    account_id: str = "acc-card",
    *,
    statement: float | None = 1234.56,
    statement_date: str | None = "2026-10-03",
    minimum: float | None = 35,
    due: str | None = "2026-10-28",
    last_payment: float | None = 980.10,
    last_payment_date: str | None = "2026-09-26",
    overdue: bool | None = False,
) -> dict[str, Any]:
    """A /liabilities/get credit entry."""
    return {
        "account_id": account_id, "aprs": [], "is_overdue": overdue,
        "last_payment_amount": last_payment, "last_payment_date": last_payment_date,
        "last_statement_issue_date": statement_date, "last_statement_balance": statement,
        "minimum_payment_amount": minimum, "next_payment_due_date": due,
    }  # fmt: skip


def txn(
    transaction_id: str,
    amount: float,
    day: str,
    *,
    account_id: str = "acc-card",
    authorized: str | None = None,
    pending: bool = False,
    pending_id: str | None = None,
    merchant: str | None = "Blue Bottle Coffee",
) -> dict[str, Any]:
    description = (merchant or "ACH DEPOSIT").upper()
    return {
        "transaction_id": transaction_id, "account_id": account_id, "amount": amount,
        "iso_currency_code": "USD", "unofficial_currency_code": None,
        "date": day, "authorized_date": authorized, "pending": pending, "pending_transaction_id": pending_id,
        "merchant_name": merchant, "name": description, "original_description": f"{description} #0042",
        "merchant_entity_id": None, "payment_channel": "in store", "logo_url": None, "website": None,
        "personal_finance_category": {"primary": "FOOD_AND_DRINK", "detailed": "FOOD_AND_DRINK_COFFEE",
                                      "confidence_level": "VERY_HIGH", "version": "v2"},
    }  # fmt: skip


def page(
    *,
    next_cursor: str,
    added: list[dict[str, Any]] = (),
    modified: list[dict[str, Any]] = (),
    removed: list[str] = (),
    has_more: bool = False,
    status: str = "HISTORICAL_UPDATE_COMPLETE",
) -> dict[str, Any]:
    return {
        "added": list(added), "modified": list(modified),
        "removed": [{"transaction_id": t, "account_id": "acc-card"} for t in removed],
        "accounts": [], "next_cursor": next_cursor, "has_more": has_more,
        "transactions_update_status": status, "request_id": "req",
    }  # fmt: skip
