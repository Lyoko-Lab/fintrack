from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from plaid_fakes import FakeItem, FakePlaid, account, page, txn

from fintrack import keychain
from fintrack.config import Settings
from fintrack.plaid import PlaidNotConfigured
from fintrack.scheduler import Scheduler, is_due, last_daily_mark

PDT = timezone(timedelta(hours=-7))


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=PDT)


def test_the_daily_mark_is_the_most_recent_6am():
    assert last_daily_mark(at(28, 9)) == at(28, 6)
    assert last_daily_mark(at(28, 5, 59)) == at(27, 6)


def test_due_once_per_day_after_6am():
    assert is_due(at(28, 6, 5), last_success=at(27, 6, 2), last_attempt=None)
    assert not is_due(at(28, 9), last_success=at(28, 6, 2), last_attempt=None)
    assert not is_due(at(28, 5), last_success=at(27, 6, 2), last_attempt=None)  # before today's mark


def test_a_mac_that_slept_through_6am_catches_up_when_it_wakes():
    assert is_due(at(28, 10, 30), last_success=at(27, 6, 1), last_attempt=at(27, 6, 1))


def test_failed_attempts_are_retried_at_most_every_30_minutes():
    assert not is_due(at(28, 6, 20), last_success=at(27, 6, 1), last_attempt=at(28, 6, 1))
    assert is_due(at(28, 6, 31), last_success=at(27, 6, 1), last_attempt=at(28, 6, 1))


def test_success_recorded_in_utc_is_compared_correctly_with_local_time():
    success_utc = datetime(2026, 10, 28, 13, 2, tzinfo=timezone.utc)  # 06:02 PDT
    assert not is_due(at(28, 9), last_success=success_utc, last_attempt=None)


def test_tick_runs_a_scheduled_sync_when_due(settings: Settings, db: sqlite3.Connection, plaid: FakePlaid):
    plaid.items["access-1"] = FakeItem([account("acc-card")], {None: page(added=[txn("t1", 5.75, "2026-10-27")], next_cursor="c1")})
    keychain.set_access_token("item-1", "access-1")
    db.execute("INSERT INTO items (external_id, institution_name, created_at) VALUES ('item-1', 'Chase', '2026-10-01T00:00:00Z')")
    scheduler = Scheduler(settings.db_path, plaid.client, clock=lambda: at(28, 7))

    assert scheduler.tick() is True
    assert scheduler.tick() is False  # already synced since 6am
    runs = db.execute("SELECT triggered_by, status FROM sync_runs").fetchall()
    assert [tuple(r) for r in runs] == [("schedule", "success")]
    assert db.execute("SELECT category_id FROM v_ledger").fetchone()[0] == "dining.coffee"


def test_tick_does_nothing_without_banks_or_credentials(settings: Settings, db: sqlite3.Connection):
    def unconfigured():
        raise PlaidNotConfigured("no credentials")

    assert Scheduler(settings.db_path, unconfigured, clock=lambda: at(28, 7)).tick() is False
    db.execute("INSERT INTO items (external_id, institution_name, created_at) VALUES ('item-1', 'Chase', '2026-10-01T00:00:00Z')")
    assert Scheduler(settings.db_path, unconfigured, clock=lambda: at(28, 7)).tick() is False
    assert db.execute("SELECT COUNT(*) FROM sync_runs").fetchone()[0] == 0
