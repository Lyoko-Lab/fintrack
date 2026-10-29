"""The PreToolUse hook that keeps real financial data out of Claude Code sessions."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

GUARD = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "private_data_guard.py"


def run_guard(tool_name: str, tool_input: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    event = json.dumps({"tool_name": tool_name, "tool_input": tool_input})
    return subprocess.run([sys.executable, str(GUARD)], input=event, capture_output=True, text=True)


@pytest.mark.parametrize(
    "command",
    [
        "sqlite3 data/fintrack-production.db 'SELECT * FROM transactions'",
        "cat ./data/logs/server.log",
        "tail -n 50 /Users/someone/fintrack/data/logs/server.log",
        "cd data && ls",
        "uv run python -c 'from fintrack.db import open_db; open_db(path)'",
        "uv run python -c 'import fintrack.config as c; print(c.load_settings().db_path)'",
        "security find-generic-password -s fintrack -w",
        "uv run python -c 'from fintrack import keychain; print(keychain.get_secret(\"X\"))'",
        "curl -s http://127.0.0.1:8787/api/activity",
        "curl localhost:8787/api/overview",
    ],
)
def test_commands_that_could_reveal_real_data_are_blocked(command: str):
    result = run_guard("Bash", {"command": command})
    assert result.returncode == 2
    assert "CLAUDE.md" in result.stderr


@pytest.mark.parametrize(
    "command",
    [
        "uv run pytest",
        "uv run fintrack status",
        "uv run fintrack secrets list",
        "git status --short",
        "grep -rn open_db src",
        "npm --prefix web run build",
        "lsof -nP -iTCP:8787 -sTCP:LISTEN",
        "curl -s http://127.0.0.1:8788/api/status",
    ],
)
def test_everyday_development_commands_pass(command: str):
    assert run_guard("Bash", {"command": command}).returncode == 0


def test_browser_tools_cannot_open_the_production_server():
    assert run_guard("mcp__Claude_Browser__navigate", {"url": "http://127.0.0.1:8787/"}).returncode == 2
    assert run_guard("mcp__Claude_Browser__navigate", {"url": "http://127.0.0.1:8788/"}).returncode == 0
    assert run_guard("mcp__Claude_Browser__navigate", {"url": "https://plaid.com/docs/data/"}).returncode == 0
