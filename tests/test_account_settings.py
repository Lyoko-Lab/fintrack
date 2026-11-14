from __future__ import annotations

import sqlite3
from datetime import date

import pytest
from fastapi.testclient import TestClient
from ledger_fakes import add_account, add_txn
from plaid_fakes import FakePlaid

from fintrack.account_settings import InvalidSetting, UnknownAccount, account, edit_account
from fintrack.app import create_app
from fintrack.config import Settings
from fintrack.enrich import enrich_all
from fintrack.measures import Flow, balances, total_flow
from fintrack.reports import card_payments

TODAY = date(2026, 11, 14)


@pytest.fixture
def ledger(db: sqlite3.Connection) -> dict[str, int]:
    accounts = {
        "checking": add_account(db, "Adv Plus Banking", "depository", current_cents=100_000),
        "work": add_account(db, "Business Card", "credit", current_cents=40_000, institution="Amex"),
    }
    add_txn(db, accounts["checking"], -2_000, "2026-11-10", "WHOLE FOODS MARKET", pfc="FOOD_AND_DRINK_GROCERIES")
    add_txn(db, accounts["work"], -30_000, "2026-11-10", "UNITED AIRLINES", pfc="TRAVEL_FLIGHTS")
    db.execute(
        "INSERT INTO card_statements (account_id, statement_cents, due_date, updated_at) VALUES (?, 40000, '2026-11-25', '2026-11-14T00:00:00Z')",
        (accounts["work"],),
    )
    enrich_all(db)
    return accounts


def test_a_nickname_replaces_the_banks_name_everywhere(db: sqlite3.Connection, ledger: dict[str, int]):
    edit_account(db, ledger["work"], {"nickname": "  Work card  "})

    assert (account(db, ledger["work"]) or {})["name"] == "Work card"
    assert (account(db, ledger["work"]) or {})["bank_name"] == "Business Card"
    assert {row[0] for row in db.execute("SELECT account_name FROM v_ledger")} == {"Adv Plus Banking", "Work card"}
    assert [p["account_name"] for p in card_payments(db, TODAY)] == ["Work card"]


def test_an_excluded_account_leaves_every_total(db: sqlite3.Connection, ledger: dict[str, int]):
    assert total_flow(db, date(2026, 11, 1), TODAY) == Flow(spending=32_000)
    assert balances(db)[:2] == (100_000, 40_000)

    edit_account(db, ledger["work"], {"excluded": True})

    assert total_flow(db, date(2026, 11, 1), TODAY) == Flow(spending=2_000)
    assert balances(db)[:2] == (100_000, 0)
    # Its transactions still show; only the figures leave it out.
    assert db.execute("SELECT COUNT(*) FROM v_ledger WHERE account_excluded = 1").fetchone()[0] == 1


def test_settings_back_to_the_defaults_leave_no_row(db: sqlite3.Connection, ledger: dict[str, int]):
    edit_account(db, ledger["work"], {"nickname": "Work card", "excluded": True})
    edit_account(db, ledger["work"], {"nickname": ""})
    assert (account(db, ledger["work"]) or {})["excluded"] == 1  # only the nickname went
    edit_account(db, ledger["work"], {"excluded": False})
    assert db.execute("SELECT COUNT(*) FROM account_settings").fetchone()[0] == 0


def test_bad_settings_are_refused(db: sqlite3.Connection, ledger: dict[str, int]):
    with pytest.raises(InvalidSetting):
        edit_account(db, ledger["work"], {"nickname": "x" * 61})
    with pytest.raises(InvalidSetting):
        edit_account(db, ledger["work"], {"name": "Work"})
    with pytest.raises(UnknownAccount):
        edit_account(db, 9999, {"excluded": True})


def test_account_settings_through_the_api(settings: Settings, plaid: FakePlaid, db: sqlite3.Connection):
    card = add_account(db, "Business Card", "credit", current_cents=40_000)
    api = TestClient(create_app(settings, plaid_factory=plaid.client, run_scheduler=False), base_url="http://127.0.0.1")

    edited = api.patch(f"/api/accounts/{card}", json={"nickname": "Work card", "excluded": True}).json()
    assert (edited["name"], edited["nickname"], edited["excluded"]) == ("Work card", "Work card", 1)
    assert api.get("/api/overview").json()["net_cash"]["debt"] == 0
    assert api.patch(f"/api/accounts/{card}", json={"nickname": None}).json()["name"] == "Business Card"
    assert api.patch("/api/accounts/9999", json={"excluded": True}).status_code == 404
