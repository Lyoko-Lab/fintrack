from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from fintrack import service, update
from fintrack.config import Settings


class FakeCheckout:
    """Answers the commands `fintrack update` runs, as a checkout one commit behind GitHub would."""

    def __init__(self, *, dirty: bool = False, behind: int = 1, ahead: int = 0, lock_changed: bool = False, build_fails: bool = False):
        self.head, self.remote = "aaa", "aaa" if behind == 0 else "bbb"
        self.dirty, self.behind, self.ahead = dirty, behind, ahead
        self.lock_changed, self.build_fails = lock_changed, build_fails
        self.commands: list[str] = []

    def run(self, command: Sequence[str], cwd: Path) -> str:
        tool, *args = command
        line = " ".join([Path(tool).name, *args])
        self.commands.append(line)
        if line.startswith("git status"):
            return " M src/fintrack/app.py" if self.dirty else ""
        if line == "git rev-parse HEAD":
            return self.head
        if line == "git rev-list --count HEAD..@{upstream}":
            return str(self.behind)
        if line == "git rev-list --count @{upstream}..HEAD":
            return str(self.ahead)
        if line.startswith("git merge"):
            self.head = self.remote
        if line.startswith("git describe"):
            return {"aaa": "v0.1.0", "bbb": "v0.2.0"}[args[-1]]
        if line.startswith("git diff"):
            return "web/package-lock.json" if self.lock_changed else ""
        if line.startswith("npm exec -- vite build"):
            if self.build_fails:
                raise update.UpdateError("vite build failed")
            out = Path(args[args.index("--outDir") + 1])
            out.mkdir(parents=True)
            (out / "index.html").write_text("new")
        return ""


@pytest.fixture
def web(settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("fintrack.update.shutil.which", lambda name: f"/usr/local/bin/{name}")
    monkeypatch.setattr(service, "installed", lambda: True)
    (tmp_path / "web" / "node_modules").mkdir(parents=True)
    settings.web_dist.mkdir()
    (settings.web_dist / "index.html").write_text("old")
    return tmp_path


def run_update(settings: Settings, repo: Path, checkout: FakeCheckout, restarts: list[str]) -> str:
    return update.update(settings, repo=repo, run=checkout.run, restart=lambda s: restarts.append("restart") or 4321, say=lambda _: None)


def test_update_fast_forwards_rebuilds_and_restarts(settings: Settings, web: Path):
    checkout, restarts = FakeCheckout(), []

    assert run_update(settings, web, checkout, restarts) == "v0.2.0"

    assert "git merge --ff-only @{upstream}" in checkout.commands
    assert "uv sync --locked" in checkout.commands
    assert "npm ci" not in checkout.commands  # the web lockfile didn't change
    assert (settings.web_dist / "index.html").read_text() == "new"
    assert not settings.web_dist.with_name("dist.next").exists() and not settings.web_dist.with_name("dist.old").exists()
    assert restarts == ["restart"]


def test_update_reinstalls_web_dependencies_when_their_lockfile_changed(settings: Settings, web: Path):
    checkout = FakeCheckout(lock_changed=True)
    run_update(settings, web, checkout, [])
    assert "npm ci" in checkout.commands


def test_local_commits_are_deployed_without_pulling(settings: Settings, web: Path):
    checkout, restarts = FakeCheckout(behind=0, ahead=2), []
    run_update(settings, web, checkout, restarts)
    assert not any(command.startswith("git merge") for command in checkout.commands)
    assert restarts == ["restart"]


@pytest.mark.parametrize(
    ("checkout", "message"),
    [(FakeCheckout(dirty=True), "uncommitted changes"), (FakeCheckout(behind=1, ahead=1), "both moved on")],
)
def test_update_stops_before_touching_anything(settings: Settings, web: Path, checkout: FakeCheckout, message: str):
    restarts: list[str] = []
    with pytest.raises(update.UpdateError, match=message):
        run_update(settings, web, checkout, restarts)
    assert not any(command.startswith(("git merge", "uv", "npm")) for command in checkout.commands)
    assert restarts == []


def test_a_failed_build_leaves_the_running_app_alone(settings: Settings, web: Path):
    restarts: list[str] = []
    with pytest.raises(update.UpdateError):
        run_update(settings, web, FakeCheckout(build_fails=True), restarts)
    assert (settings.web_dist / "index.html").read_text() == "old"
    assert restarts == []
