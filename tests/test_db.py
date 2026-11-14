from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest
from ledger_fakes import add_account, add_txn

from fintrack import db
from fintrack.db import open_db


def migrations_up_to(last: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Let open_db see only the migrations up to `last`, as an older version of the app would."""
    folder = tmp_path / f"migrations-{last}"
    shutil.copytree(Path(db.__file__).parent / "migrations", folder, ignore=shutil.ignore_patterns("__pycache__"))
    for script in folder.glob("*.sql"):
        if int(script.name.split("_", 1)[0]) > last:
            script.unlink()
    real = db.resources.files
    monkeypatch.setattr(db.resources, "files", lambda package: folder if package == "fintrack.migrations" else real(package))


def test_card_statements_carry_over_into_their_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with monkeypatch.context() as old_app:
        migrations_up_to(5, tmp_path, old_app)
        conn = open_db(tmp_path / "ledger.db")
        card = add_account(conn, "Card", "credit")
        conn.execute(
            """
            INSERT INTO card_statements (account_id, statement_date, statement_cents, due_date, updated_at)
            VALUES (?, '2026-10-31', 25000, '2026-11-25', '2026-11-14T06:00:00Z')
            """,
            (card,),
        )
        conn.close()

    conn = open_db(tmp_path / "ledger.db")

    rows = conn.execute("SELECT account_id, statement_cents, due_date, first_seen_at, updated_at FROM v_card_statements")
    assert [tuple(row) for row in rows] == [(card, 25000, "2026-11-25", "2026-11-14T06:00:00Z", "2026-11-14T06:00:00Z")]


def test_views_are_created_afresh_whenever_the_database_is_opened(tmp_path: Path):
    conn = open_db(tmp_path / "ledger.db")
    conn.execute("DROP VIEW v_ledger")
    conn.close()
    assert open_db(tmp_path / "ledger.db").execute("SELECT COUNT(*) FROM v_ledger").fetchone()[0] == 0


def test_later_migrations_run_with_the_views_out_of_the_way(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    migrations = tmp_path / "migrations"
    shutil.copytree(Path(db.__file__).parent / "migrations", migrations, ignore=shutil.ignore_patterns("__pycache__"))
    (migrations / "0099_look.sql").write_text("CREATE TABLE views_seen AS SELECT COUNT(*) AS n FROM sqlite_master WHERE type = 'view';")
    real = db.resources.files
    monkeypatch.setattr(db.resources, "files", lambda package: migrations if package == "fintrack.migrations" else real(package))

    conn = open_db(tmp_path / "ledger.db")

    assert conn.execute("SELECT n FROM views_seen").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM v_ledger").fetchone()[0] == 0  # and back afterwards


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def test_a_new_database_is_migrated_without_a_backup(tmp_path: Path):
    open_db(tmp_path / "ledger.db").close()
    assert not (tmp_path / "backups").exists()


def test_existing_data_is_backed_up_before_a_migration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    latest = schema_version(open_db(tmp_path / "current.db"))
    with monkeypatch.context() as old_app:  # a database from before the newest migration
        migrations_up_to(latest - 1, tmp_path, old_app)
        conn = open_db(tmp_path / "ledger.db")
        add_txn(conn, add_account(conn, "Checking", "depository"), -1234, "2026-10-01", "COFFEE")
        conn.close()

    conn = open_db(tmp_path / "ledger.db")

    assert schema_version(conn) == latest
    [copy] = (tmp_path / "backups").glob(f"ledger.v{latest - 1}.*.db")
    saved = sqlite3.connect(copy)
    assert saved.execute("SELECT amount_cents FROM transactions").fetchall() == [(-1234,)]
    assert schema_version(saved) == latest - 1


def test_an_up_to_date_database_isnt_backed_up_again(tmp_path: Path):
    open_db(tmp_path / "ledger.db").close()
    open_db(tmp_path / "ledger.db").close()
    assert not (tmp_path / "backups").exists()


def test_only_the_latest_backups_are_kept(tmp_path: Path):
    conn = open_db(tmp_path / "ledger.db")
    folder = tmp_path / "backups"
    folder.mkdir()
    # Older copies, one from a much earlier schema: by name v12 would sort before v4, by time it doesn't.
    for n, version in enumerate([12, 4, 4, 4, 4, 4]):
        (folder / f"ledger.v{version}.20260101T00000{n}000000Z.db").write_text("")

    newest = db.backup(conn, 5)

    kept = sorted(path.name for path in folder.iterdir())
    assert len(kept) == db.BACKUPS_KEPT and newest is not None and newest.name in kept
    assert "ledger.v12.20260101T000000000000Z.db" not in kept
