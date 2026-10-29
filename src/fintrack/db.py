"""SQLite connections and schema migrations.

The schema lives in numbered SQL files under migrations/, applied in order and
tracked with PRAGMA user_version.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Autocommit mode: multi-statement writes go through transaction().
    # check_same_thread=False because FastAPI may open a connection on one worker thread and use it on another.
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def open_db(path: Path) -> sqlite3.Connection:
    conn = connect(path)
    migrate(conn)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    # IMMEDIATE takes the write lock up front, so a concurrent writer waits instead of failing mid-transaction.
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations and return the resulting schema version."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    scripts = sorted(
        (f for f in resources.files("fintrack.migrations").iterdir() if f.name.endswith(".sql")),
        key=lambda f: f.name,
    )
    for script in scripts:
        target = int(script.name.split("_", 1)[0])
        if target <= version:
            continue
        try:
            conn.executescript(f"BEGIN;\n{script.read_text()}\nPRAGMA user_version = {target};\nCOMMIT;")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        version = target
    return version


def utcnow() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
