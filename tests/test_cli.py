import pytest

from fintrack import keychain
from fintrack.cli import main


def test_a_secret_typed_on_the_command_line_is_refused_with_guidance(capsys: pytest.CaptureFixture[str]):
    assert main(["secrets", "set", "PLAID_CLIENT_ID", "abc123"]) == 2
    assert keychain.get_secret("PLAID_CLIENT_ID") is None
    assert "uv run fintrack secrets set PLAID_CLIENT_ID" in capsys.readouterr().err


def test_a_secret_is_read_from_the_hidden_prompt(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("getpass.getpass", lambda prompt: "  abc123\n")
    assert main(["secrets", "set", "PLAID_CLIENT_ID"]) == 0
    assert keychain.get_secret("PLAID_CLIENT_ID") == "abc123"
