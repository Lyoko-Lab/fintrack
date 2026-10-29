#!/usr/bin/env python3
"""PreToolUse hook: keep the real financial data out of Claude Code sessions.

Everything a tool returns is sent to Anthropic, so tool calls that could read the
production database, its logs, the Keychain or the production web server are
refused before they run (exit code 2). It is a seatbelt, not a sandbox: CLAUDE.md
states the rule, and this catches the usual ways of breaking it by accident.
"""

from __future__ import annotations

import json
import re
import sys

PRODUCTION_SERVER = (
    re.compile(r"(?:127\.0\.0\.1|localhost|0\.0\.0\.0|\[::1\]):8787(?!\d)"),
    "正式环境的网页和 API（端口 8787）",
)
SHELL_RULES = (
    (
        re.compile(r"(?:^|[\s'\"=(;|&<>])(?:\./)?data/|\bcd\s+(?:\./)?data\b|(?:fintrack|PROJECT_DIR\}?)/data\b"),
        "data/ 目录（数据库和日志）",
    ),
    (
        re.compile(r"\bsqlite3\b|fintrack-production|\.db(?:-wal|-shm)?\b|\bopen_db\s*\(|\.db_path\b"),
        "账本数据库",
    ),
    (
        re.compile(
            r"\bsecurity\s+(?:find-generic-password|find-internet-password|dump-keychain|export)\b"
            r"|\bkeyring\s+get\b|\bget_(?:secret|access_token)\s*\("
        ),
        "Keychain 里的密钥",
    ),
    PRODUCTION_SERVER,
)


def violation(tool_name: str, tool_input: dict) -> str | None:
    """What the call would touch, or None when it is fine."""
    text = "\n".join(value for value in tool_input.values() if isinstance(value, str))
    # Browser URLs legitimately contain paths like /data/, so only the server rule applies to them.
    rules = SHELL_RULES if tool_name == "Bash" else (PRODUCTION_SERVER,)
    for pattern, what in rules:
        if pattern.search(text):
            return what
    return None


def main() -> int:
    event = json.load(sys.stdin)
    what = violation(event.get("tool_name", ""), event.get("tool_input") or {})
    if what is None:
        return 0
    print(
        f"已拦截：这个操作会接触{what}。真实财务数据不能进入 Claude Code 的对话，规则见 CLAUDE.md「隐私」一节。",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
