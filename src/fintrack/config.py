"""Runtime settings.

Non-secret settings come from environment variables, optionally loaded from a
`.env` file at the repo root. Secrets live in the macOS Keychain (see keychain.py).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]

PLAID_HOSTS = {
    "sandbox": "https://sandbox.plaid.com",
    "production": "https://production.plaid.com",
}


@dataclass(frozen=True)
class Settings:
    env: str  # "sandbox" or "production"
    data_dir: Path
    port: int = 8787
    web_dist: Path = REPO_ROOT / "web" / "dist"  # the built React app

    @property
    def db_path(self) -> Path:
        # Sandbox and production never share a database, so test Items can't leak into the real ledger.
        return self.data_dir / f"fintrack-{self.env}.db"

    @property
    def plaid_host(self) -> str:
        return PLAID_HOSTS[self.env]

    @property
    def plaid_secret_name(self) -> str:
        return f"PLAID_SECRET_{self.env.upper()}"


def load_settings() -> Settings:
    load_dotenv(REPO_ROOT / ".env")
    env = os.environ.get("FINTRACK_ENV", "sandbox")
    if env not in PLAID_HOSTS:
        raise ValueError(f"FINTRACK_ENV must be one of {sorted(PLAID_HOSTS)}, got {env!r}")
    data_dir = Path(os.environ.get("FINTRACK_DATA_DIR", "data")).expanduser()
    if not data_dir.is_absolute():
        data_dir = REPO_ROOT / data_dir
    return Settings(env=env, data_dir=data_dir, port=int(os.environ.get("FINTRACK_PORT", "8787")))
