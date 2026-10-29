"""Daily sync inside the server process.

Rather than firing at exactly 06:00 (and missing it whenever the Mac sleeps), it checks
every few minutes whether a sync has succeeded since the most recent 06:00, and runs
one if not. Failed attempts are retried, but not more often than every 30 minutes.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime, time, timedelta
from pathlib import Path

from .db import connect
from .plaid import PlaidClient, PlaidNotConfigured
from .sync import SyncInProgress, run_sync

log = logging.getLogger(__name__)

DAILY_AT = time(6, 0)
RETRY_AFTER = timedelta(minutes=30)


def last_daily_mark(now: datetime) -> datetime:
    mark = datetime.combine(now.date(), DAILY_AT, tzinfo=now.tzinfo)
    return mark if mark <= now else mark - timedelta(days=1)


def is_due(now: datetime, last_success: datetime | None, last_attempt: datetime | None) -> bool:
    if last_success is not None and last_success >= last_daily_mark(now):
        return False
    return last_attempt is None or now - last_attempt >= RETRY_AFTER


def _parse(timestamp: str | None) -> datetime | None:
    return datetime.fromisoformat(timestamp) if timestamp else None


class Scheduler:
    def __init__(
        self,
        db_path: Path,
        plaid_factory: Callable[[], PlaidClient],
        *,
        interval: float = 300,
        clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    ) -> None:
        self._db_path = db_path
        self._plaid_factory = plaid_factory
        self._interval = interval
        self._clock = clock
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="fintrack-scheduler", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=10)

    def _loop(self) -> None:
        delay = 5.0  # first check shortly after startup, so a missed morning sync catches up right away
        while not self._stop.wait(delay):
            self.tick()
            delay = self._interval

    def tick(self) -> bool:
        """Run a sync if one is due. Returns whether a sync ran."""
        conn = connect(self._db_path)
        try:
            last_success = conn.execute(
                "SELECT MAX(started_at) FROM sync_runs WHERE status IN ('success', 'partial')"
            ).fetchone()[0]
            last_attempt = conn.execute(
                "SELECT MAX(started_at) FROM sync_runs WHERE triggered_by = 'schedule'"
            ).fetchone()[0]
            if not is_due(self._clock(), _parse(last_success), _parse(last_attempt)):
                return False
            if conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 0:
                return False
            run_sync(conn, self._plaid_factory(), triggered_by="schedule")
            return True
        except (PlaidNotConfigured, SyncInProgress) as e:
            log.info("scheduled sync skipped: %s", e)
            return False
        except Exception:
            log.exception("scheduled sync failed")
            return False
        finally:
            conn.close()
