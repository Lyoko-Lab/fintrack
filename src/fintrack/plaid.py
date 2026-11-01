"""Plaid connector: a thin HTTP client plus normalization into Ledger records.

Only the endpoints Fintrack uses are wrapped. Response bodies are parsed with
Decimal so amounts never pass through binary floats, and each response's raw
text is kept for the Raw layer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any

import httpx2

from . import keychain

if TYPE_CHECKING:
    from .config import Settings

API_VERSION = "2020-09-14"
# Non-OAuth test bank, used by `fintrack sandbox-link`.
SANDBOX_INSTITUTION = ("ins_109508", "First Platypus Bank")
MUTATION_DURING_PAGINATION = "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION"


class PlaidNotConfigured(RuntimeError):
    pass


class PlaidError(Exception):
    def __init__(self, status_code: int, body: dict[str, Any]):
        self.status_code = status_code
        self.error_type: str | None = body.get("error_type")
        self.error_code: str | None = body.get("error_code")
        self.error_message: str | None = body.get("error_message")
        self.request_id: str | None = body.get("request_id")
        code = self.error_code or f"HTTP {status_code}"
        super().__init__(f"{code}: {self.error_message or 'Plaid request failed'}")


@dataclass(frozen=True)
class PlaidResponse:
    body: dict[str, Any]
    raw: str  # response text exactly as received


class PlaidClient:
    def __init__(
        self, base_url: str, client_id: str, secret: str, *, transport: httpx2.BaseTransport | None = None
    ) -> None:
        self._http = httpx2.Client(
            base_url=base_url,
            headers={"PLAID-CLIENT-ID": client_id, "PLAID-SECRET": secret, "Plaid-Version": API_VERSION},
            timeout=60.0,
            transport=transport,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> PlaidClient:
        client_id = keychain.get_secret("PLAID_CLIENT_ID")
        secret = keychain.get_secret(settings.plaid_secret_name)
        if not client_id or not secret:
            raise PlaidNotConfigured(
                "还没有配置 Plaid 密钥，请运行 `uv run fintrack secrets set PLAID_CLIENT_ID` "
                f"和 `uv run fintrack secrets set {settings.plaid_secret_name}`"
            )
        return cls(settings.plaid_host, client_id, secret)

    def post(self, path: str, payload: dict[str, Any]) -> PlaidResponse:
        response = self._http.post(path, json=payload)
        try:
            body = json.loads(response.text, parse_float=Decimal)
        except ValueError:
            body = None
        if response.status_code != 200 or not isinstance(body, dict):
            raise PlaidError(response.status_code, body if isinstance(body, dict) else {})
        return PlaidResponse(body, response.text)

    def create_link_token(self, *, access_token: str | None = None) -> str:
        payload: dict[str, Any] = {
            "client_name": "Fintrack",
            "user": {"client_user_id": "fintrack-owner"},
            "country_codes": ["US"],
            "language": "en",
        }
        if access_token:
            # Update mode repairs an existing Item (e.g. after ITEM_LOGIN_REQUIRED) without creating a new one.
            payload["access_token"] = access_token
        else:
            # No "auth": Fintrack never needs, and so never holds, full account or routing numbers.
            payload["products"] = ["transactions"]
            payload["optional_products"] = ["liabilities"]
            # History depth is fixed when the Item is created, so ask for Plaid's maximum (2 years) up front.
            payload["transactions"] = {"days_requested": 730}
        return self.post("/link/token/create", payload).body["link_token"]

    def exchange_public_token(self, public_token: str) -> tuple[str, str]:
        """Return (item_id, access_token)."""
        body = self.post("/item/public_token/exchange", {"public_token": public_token}).body
        return body["item_id"], body["access_token"]

    def get_accounts(self, access_token: str) -> PlaidResponse:
        return self.post("/accounts/get", {"access_token": access_token})

    def get_liabilities(self, access_token: str) -> PlaidResponse:
        return self.post("/liabilities/get", {"access_token": access_token})

    def sync_transactions(self, access_token: str, cursor: str | None) -> PlaidResponse:
        payload: dict[str, Any] = {
            "access_token": access_token,
            "count": 500,
            "options": {"include_original_description": True},
        }
        if cursor:
            payload["cursor"] = cursor
        return self.post("/transactions/sync", payload)

    def create_sandbox_public_token(self, username: str, institution_id: str) -> str:
        payload = {
            "institution_id": institution_id,
            "initial_products": ["transactions"],
            "options": {
                "override_username": username,
                "override_password": "pass_good",
                "transactions": {"days_requested": 730},
            },
        }
        return self.post("/sandbox/public_token/create", payload).body["public_token"]


def to_cents(value: Decimal | int | float | str) -> int:
    return int((Decimal(str(value)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _optional_cents(value: Decimal | int | float | str | None) -> int | None:
    return None if value is None else to_cents(value)


@dataclass(frozen=True)
class AccountRecord:
    external_id: str
    name: str
    official_name: str | None
    mask: str | None
    type: str
    subtype: str | None
    currency: str | None
    current_cents: int | None
    available_cents: int | None
    limit_cents: int | None


@dataclass(frozen=True)
class TransactionRecord:
    external_id: str
    account_external_id: str
    pending: bool
    pending_external_id: str | None
    amount_cents: int
    currency: str | None
    transaction_date: str
    authorized_date: str | None
    posted_date: str
    merchant_name: str | None
    description: str | None
    original_description: str | None
    merchant_entity_id: str | None
    payment_channel: str | None
    pfc_primary: str | None
    pfc_detailed: str | None
    pfc_confidence: str | None
    logo_url: str | None
    website: str | None


@dataclass(frozen=True)
class CardStatementRecord:
    """A credit card's latest statement and the payment due on it. Amounts are owed, so positive."""

    account_external_id: str
    statement_date: str | None
    statement_cents: int | None
    minimum_cents: int | None
    due_date: str | None
    last_payment_cents: int | None
    last_payment_date: str | None
    is_overdue: bool | None


def parse_card_statements(liabilities: dict[str, Any]) -> list[CardStatementRecord]:
    """The credit cards in a /liabilities/get body (mortgages and student loans aren't tracked)."""
    return [
        CardStatementRecord(
            account_external_id=card["account_id"],
            statement_date=card.get("last_statement_issue_date"),
            statement_cents=_optional_cents(card.get("last_statement_balance")),
            minimum_cents=_optional_cents(card.get("minimum_payment_amount")),
            due_date=card.get("next_payment_due_date"),
            last_payment_cents=_optional_cents(card.get("last_payment_amount")),
            last_payment_date=card.get("last_payment_date"),
            is_overdue=card.get("is_overdue"),
        )
        for card in (liabilities.get("liabilities") or {}).get("credit") or []
        if card.get("account_id")
    ]


def parse_account(account: dict[str, Any]) -> AccountRecord:
    balances = account.get("balances") or {}
    return AccountRecord(
        external_id=account["account_id"],
        name=account.get("name") or account.get("official_name") or "Account",
        official_name=account.get("official_name"),
        mask=account.get("mask"),
        type=account.get("type") or "other",
        subtype=account.get("subtype"),
        currency=balances.get("iso_currency_code") or balances.get("unofficial_currency_code"),
        current_cents=_optional_cents(balances.get("current")),
        available_cents=_optional_cents(balances.get("available")),
        limit_cents=_optional_cents(balances.get("limit")),
    )


def parse_transaction(txn: dict[str, Any]) -> TransactionRecord:
    category = txn.get("personal_finance_category") or {}
    authorized_date = txn.get("authorized_date")
    return TransactionRecord(
        external_id=txn["transaction_id"],
        account_external_id=txn["account_id"],
        pending=bool(txn.get("pending")),
        pending_external_id=txn.get("pending_transaction_id"),
        # Plaid: positive means money left the account. Fintrack: positive means money came in.
        amount_cents=-to_cents(txn["amount"]),
        currency=txn.get("iso_currency_code") or txn.get("unofficial_currency_code"),
        transaction_date=authorized_date or txn["date"],
        authorized_date=authorized_date,
        posted_date=txn["date"],
        merchant_name=txn.get("merchant_name"),
        description=txn.get("name"),
        original_description=txn.get("original_description"),
        merchant_entity_id=txn.get("merchant_entity_id"),
        payment_channel=txn.get("payment_channel"),
        pfc_primary=category.get("primary"),
        pfc_detailed=category.get("detailed"),
        pfc_confidence=category.get("confidence_level"),
        logo_url=txn.get("logo_url"),
        website=txn.get("website"),
    )


@dataclass
class TransactionChanges:
    """Everything /transactions/sync reported since a cursor, across all pages."""

    next_cursor: str
    update_status: str | None = None
    added: list[TransactionRecord] = field(default_factory=list)
    modified: list[TransactionRecord] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    accounts: list[AccountRecord] = field(default_factory=list)
    pages: list[str] = field(default_factory=list)


def fetch_transaction_changes(
    client: PlaidClient, access_token: str, cursor: str | None, *, attempts: int = 3
) -> TransactionChanges:
    """Pull every page since `cursor`.

    The caller applies the result in one database transaction, so an interrupted
    sync never half-applies an update; the next run restarts from the old cursor.
    """
    for attempt in range(attempts):
        changes = TransactionChanges(next_cursor=cursor or "")
        try:
            while True:
                page = client.sync_transactions(access_token, changes.next_cursor or None)
                body = page.body
                changes.pages.append(page.raw)
                changes.added += [parse_transaction(t) for t in body["added"]]
                changes.modified += [parse_transaction(t) for t in body["modified"]]
                changes.removed += [r["transaction_id"] for r in body["removed"]]
                changes.accounts += [parse_account(a) for a in body.get("accounts", [])]
                changes.update_status = body.get("transactions_update_status")
                changes.next_cursor = body["next_cursor"]
                if not body["has_more"]:
                    return changes
        except PlaidError as e:
            # Plaid's rule for this error: restart the whole loop from the cursor the update began with.
            if e.error_code != MUTATION_DURING_PAGINATION or attempt == attempts - 1:
                raise
    raise AssertionError("unreachable")
