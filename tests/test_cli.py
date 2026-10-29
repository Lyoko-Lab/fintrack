import sqlite3

import pytest
from ledger_fakes import add_account, add_txn

from fintrack import keychain
from fintrack.cli import main
from fintrack.config import Settings


def test_a_secret_typed_on_the_command_line_is_refused_with_guidance(capsys: pytest.CaptureFixture[str]):
    assert main(["secrets", "set", "PLAID_CLIENT_ID", "abc123"]) == 2
    assert keychain.get_secret("PLAID_CLIENT_ID") is None
    assert "uv run fintrack secrets set PLAID_CLIENT_ID" in capsys.readouterr().err


def test_a_secret_is_read_from_the_hidden_prompt(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("getpass.getpass", lambda prompt: "  abc123\n")
    assert main(["secrets", "set", "PLAID_CLIENT_ID"]) == 0
    assert keychain.get_secret("PLAID_CLIENT_ID") == "abc123"


def test_status_reports_sync_health_without_personal_data(
    db: sqlite3.Connection, settings: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    monkeypatch.setenv("FINTRACK_ENV", settings.env)
    monkeypatch.setenv("FINTRACK_DATA_DIR", str(settings.data_dir))
    checking = add_account(db, "Adv Plus Banking", "depository", mask="4821", current_cents=123_456)
    add_account(db, "Sapphire Preferred", "credit", mask="7781", current_cents=-5_678, institution="Chase")
    add_txn(db, checking, -1_234, "2024-11-02", "SQ *BLUE BOTTLE")
    add_txn(db, checking, 250_000, "2026-10-15", "ACME PAYROLL PPD ID 99881")

    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "depository/-  交易 2 笔  2024-11-02 ~ 2026-10-15" in out
    assert "credit/-  交易 0 笔  —" in out
    for private in ("Adv Plus", "Sapphire", "4821", "7781", "1,234.56", "56.78", "BLUE BOTTLE", "PAYROLL"):
        assert private not in out
