from decimal import Decimal

import httpx2
import pytest
from plaid_fakes import FakePlaid, card, txn

from fintrack.plaid import CardStatementRecord, PlaidClient, PlaidError, parse_card_statements, parse_transaction, to_cents


def test_card_statements_come_from_the_credit_liabilities_only():
    body = {
        "liabilities": {
            "credit": [card("acc-card", statement=Decimal("1234.56"), minimum=Decimal("35")), {"account_id": None}],
            "mortgage": [{"account_id": "acc-home"}],
            "student": None,
        }
    }
    assert parse_card_statements(body) == [
        CardStatementRecord("acc-card", "2026-10-03", 123456, 3500, "2026-10-28", 98010, "2026-09-26", False)
    ]
    assert parse_card_statements({"liabilities": {"credit": None}}) == []


def test_to_cents_is_exact():
    assert to_cents(Decimal("19.99")) == 1999
    assert to_cents(Decimal("0.125")) == 13
    assert to_cents(0.1) == 10
    assert to_cents(Decimal("-2500")) == -250000


def test_amounts_are_signed_from_the_owners_point_of_view():
    assert parse_transaction(txn("t1", 5.75, "2026-10-02")).amount_cents == -575  # card purchase: money out
    assert parse_transaction(txn("t2", -2500, "2026-10-01")).amount_cents == 250000  # payroll: money in


def test_transaction_date_is_when_it_happened_not_when_it_posted():
    purchase = parse_transaction(txn("t1", 42, "2026-11-02", authorized="2026-10-31"))
    assert (purchase.transaction_date, purchase.posted_date) == ("2026-10-31", "2026-11-02")
    assert parse_transaction(txn("t2", 42, "2026-11-02")).transaction_date == "2026-11-02"


def test_new_link_token_asks_for_two_years_and_no_account_numbers(plaid: FakePlaid):
    plaid.client().create_link_token()
    path, body = plaid.requests[-1]
    assert path == "/link/token/create"
    assert body["products"] == ["transactions"]
    assert body["optional_products"] == ["liabilities"]
    assert body["transactions"] == {"days_requested": 730}


def test_update_mode_link_token_reuses_the_item(plaid: FakePlaid):
    plaid.client().create_link_token(access_token="access-1")
    _, body = plaid.requests[-1]
    assert body["access_token"] == "access-1"
    assert "products" not in body


def test_error_response_raises_plaid_error(plaid: FakePlaid):
    plaid.fail_next("/accounts/get", "ITEM_LOGIN_REQUIRED")
    with pytest.raises(PlaidError) as raised:
        plaid.client().get_accounts("access-1")
    assert raised.value.error_code == "ITEM_LOGIN_REQUIRED"


def test_non_json_error_still_raises_plaid_error():
    transport = httpx2.MockTransport(lambda request: httpx2.Response(502, text="<html>Bad Gateway</html>"))
    client = PlaidClient("https://sandbox.plaid.com", "client-id", "secret", transport=transport)
    with pytest.raises(PlaidError) as raised:
        client.get_accounts("access-1")
    assert raised.value.status_code == 502
