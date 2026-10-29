"""Secrets live in the macOS Keychain under service "fintrack", never in files or the database.

Environment variables override Keychain values for the user-managed secrets, so
tests or another host can inject them.
"""

from __future__ import annotations

import os

import keyring

SERVICE = "fintrack"

# Secrets the user sets with `fintrack secrets set`.
USER_SECRETS = (
    "PLAID_CLIENT_ID",
    "PLAID_SECRET_SANDBOX",
    "PLAID_SECRET_PRODUCTION",
    "ANTHROPIC_API_KEY",
)


def get_secret(name: str) -> str | None:
    return os.environ.get(name) or keyring.get_password(SERVICE, name)


def set_secret(name: str, value: str) -> None:
    keyring.set_password(SERVICE, name, value)


# Plaid access tokens are keyed by Item. Losing one means re-linking the bank, which
# burns a Plaid Item permanently, so they are stored only here and never deleted.
def get_access_token(item_external_id: str) -> str | None:
    return keyring.get_password(SERVICE, f"plaid-access-token:{item_external_id}")


def set_access_token(item_external_id: str, token: str) -> None:
    keyring.set_password(SERVICE, f"plaid-access-token:{item_external_id}", token)
