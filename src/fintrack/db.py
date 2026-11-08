"""SQLite connections and schema migrations.

The schema lives in numbered SQL files under migrations/, applied in order and
tracked with PRAGMA user_version. Before migrating a database that already holds
data, a copy goes to backups/ beside it.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

BACKUPS_KEPT = 5


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
    pending = [script for script in scripts if int(script.name.split("_", 1)[0]) > version]
    if pending and version > 0:
        backup(conn, version)
    for script in pending:
        target = int(script.name.split("_", 1)[0])
        try:
            conn.executescript(f"BEGIN;\n{script.read_text()}\nPRAGMA user_version = {target};\nCOMMIT;")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        version = target
    return version


def backup(conn: sqlite3.Connection, version: int) -> Path | None:
    """Copy the database to backups/<name>.v<version>.<time>.db, keeping the latest few; None for an in-memory one.

    A migration that fails is rolled back, but one that runs and gets the data wrong would commit; the copy
    taken before it is the way back. SQLite's backup API copies a consistent snapshot even while the
    server has the database open.
    """
    path = Path(conn.execute("PRAGMA database_list").fetchone()[2] or "")
    if not path.name:
        return None
    folder = path.parent / "backups"
    folder.mkdir(exist_ok=True)
    target = folder / f"{path.stem}.v{version}.{datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}.db"
    copy = sqlite3.connect(target)
    try:
        conn.backup(copy)
    finally:
        copy.close()
    def taken_at(copy: Path) -> str:
        return copy.name.rsplit(".", 2)[1]  # the time in <name>.v<version>.<time>.db; by name, v10 would come before v4

    for old in sorted(folder.glob(f"{path.stem}.v*.db"), key=taken_at)[:-BACKUPS_KEPT]:
        old.unlink()
    return target


def utcnow() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
