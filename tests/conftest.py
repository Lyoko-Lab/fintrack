from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import keyring
import pytest
from keyring.backend import KeyringBackend
from plaid_fakes import FakePlaid

from fintrack import keychain
from fintrack.config import Settings
from fintrack.db import open_db


class MemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self) -> None:
        super().__init__()
        self.passwords: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.passwords.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.passwords[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.passwords.pop((service, username), None)


@pytest.fixture(autouse=True)
def memory_keyring(monkeypatch: pytest.MonkeyPatch) -> Iterator[MemoryKeyring]:
    """Keep every test away from the real Keychain and from secrets in the environment."""
    for name in keychain.USER_SECRETS:
        monkeypatch.delenv(name, raising=False)
    backend = MemoryKeyring()
    previous = keyring.get_keyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(env="sandbox", data_dir=tmp_path, web_dist=tmp_path / "dist")


@pytest.fixture
def db(settings: Settings) -> Iterator[sqlite3.Connection]:
    conn = open_db(settings.db_path)
    yield conn
    conn.close()


@pytest.fixture
def plaid() -> FakePlaid:
    return FakePlaid()
