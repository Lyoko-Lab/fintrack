from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from fintrack import service, update
from fintrack.config import Settings


class FakeRepo:
    """Answers the commands `fintrack update` runs, for a linear history of commits c1, c2, …"""

    def __init__(
        self,
        commits: int = 4,
        *,
        head: str = "c1",
        detached: bool = False,
        branch: str | None = None,  # where main points, when HEAD is detached
        upstream: str | None = None,
        tags: dict[str, str] | None = None,
        migrations: dict[str, int] | None = None,  # migration files at each commit (default: 5 everywhere)
        dirty: bool = False,
        diverged: bool = False,
        lock_changed: bool = False,
        build_fails: bool = False,
    ):
        self.history = [f"c{i}" for i in range(1, commits + 1)]
        self.head, self.detached = head, detached
        self.branch = branch or head
        self.upstream = upstream or self.branch
        self.tags = tags or {}
        self.migrations = migrations or {}
        self.dirty, self.diverged = dirty, diverged
        self.lock_changed, self.build_fails = lock_changed, build_fails
        self.commands: list[str] = []

    def resolve(self, ref: str) -> str:
        ref = ref.removesuffix("^{commit}")
        return {"HEAD": self.head, "@{upstream}": self.upstream}.get(ref) or self.tags.get(ref) or ref

    def run(self, command: Sequence[str], cwd: Path) -> str:
        tool, *args = command
        line = " ".join([Path(tool).name, *args])
        self.commands.append(line)
        if tool != "git":
            if line.startswith("npm exec -- vite build"):
                if self.build_fails:
                    raise update.UpdateError("vite build failed")
                out = Path(args[args.index("--outDir") + 1])
                out.mkdir(parents=True)
                (out / "index.html").write_text("new")
            return ""
        match args:
            case ["status", *_]:
                return " M src/fintrack/app.py" if self.dirty else ""
            case ["rev-parse", "--abbrev-ref", "HEAD"]:
                return "HEAD" if self.detached else "main"
            case ["rev-parse", ref]:
                return self.resolve(ref)
            case ["rev-list", "--count", spec]:
                start, end = (self.resolve(ref) for ref in spec.split(".."))
                if self.diverged and {start, end} == {self.head, self.upstream}:
                    return "1"
                return str(max(0, self.history.index(end) - self.history.index(start)))
            case ["tag", "--list", pattern]:
                return "\n".join(tag for tag in self.tags if pattern == "v*" or tag == pattern)
            case ["switch", "--detach", tag]:
                self.head, self.detached = self.tags[tag], True
            case ["switch", "main"]:
                self.head, self.detached = self.branch, False
            case ["merge", "--ff-only", _]:
                self.head = self.branch = self.upstream
            case ["describe", *_, rev]:
                return next((tag for tag, commit in self.tags.items() if commit == rev), rev)
            case ["ls-tree", "--name-only", rev, _]:
                count = self.migrations.get(self.resolve(rev), 5)
                return "\n".join(f"src/fintrack/migrations/{n:04d}_step.sql" for n in range(1, count + 1))
            case ["diff", *_]:
                return "web/package-lock.json" if self.lock_changed else ""
        return ""


@pytest.fixture
def repo(settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("fintrack.update.shutil.which", lambda name: f"/usr/local/bin/{name}")
    monkeypatch.setattr(service, "installed", lambda: True)
    (tmp_path / "web" / "node_modules").mkdir(parents=True)
    settings.web_dist.mkdir()
    (settings.web_dist / "index.html").write_text("old")
    return tmp_path


def run_update(settings: Settings, repo: Path, fake: FakeRepo, restarts: list[str], **options) -> str:
    def restart(_: Settings) -> int:
        restarts.append("restart")
        return 4321

    return update.update(settings, repo=repo, run=fake.run, restart=restart, say=lambda _: None, **options)


def test_update_goes_to_the_latest_stable_release(settings: Settings, repo: Path):
    # v0.10.0 is newer than v0.9.0, and a release candidate is never picked unasked.
    fake = FakeRepo(head="c1", tags={"v0.9.0": "c2", "v0.10.0": "c3", "v0.11.0-rc.1": "c4"})
    restarts: list[str] = []

    assert run_update(settings, repo, fake, restarts) == "v0.10.0"

    assert "git switch --detach v0.10.0" in fake.commands
    assert "uv sync --locked" in fake.commands
    assert "npm ci" not in fake.commands  # the web lockfile didn't change
    assert (settings.web_dist / "index.html").read_text() == "new"
    assert not settings.web_dist.with_name("dist.next").exists() and not settings.web_dist.with_name("dist.old").exists()
    assert restarts == ["restart"]


def test_a_version_can_be_chosen_including_an_older_one(settings: Settings, repo: Path):
    fake = FakeRepo(head="c3", detached=True, tags={"v0.1.0": "c1", "v0.2.0": "c3"})
    assert run_update(settings, repo, fake, [], version="0.1.0") == "v0.1.0"
    assert "git switch --detach v0.1.0" in fake.commands


def test_web_dependencies_are_reinstalled_when_their_lockfile_changed(settings: Settings, repo: Path):
    fake = FakeRepo(head="c1", tags={"v0.2.0": "c2"}, lock_changed=True)
    run_update(settings, repo, fake, [])
    assert "npm ci" in fake.commands


def test_dev_leaves_the_release_for_the_latest_code(settings: Settings, repo: Path):
    fake = FakeRepo(head="c2", detached=True, branch="c3", upstream="c4", tags={"v0.1.0": "c2"})
    assert run_update(settings, repo, fake, [], dev=True) == "c4"
    assert fake.commands.index("git switch main") < fake.commands.index("git merge --ff-only @{upstream}")


def test_dev_deploys_local_commits_without_pulling(settings: Settings, repo: Path):
    fake = FakeRepo(head="c3", upstream="c2")
    restarts: list[str] = []
    run_update(settings, repo, fake, restarts, dev=True)
    assert not any(command.startswith("git merge") for command in fake.commands)
    assert restarts == ["restart"]


@pytest.mark.parametrize(
    ("fake", "options", "message"),
    [
        (FakeRepo(dirty=True, tags={"v0.1.0": "c2"}), {}, "uncommitted changes"),
        (FakeRepo(head="c4", tags={"v0.1.0": "c2"}), {}, "development version"),
        (FakeRepo(head="c1"), {}, "no stable release yet"),
        (FakeRepo(tags={"v0.1.0": "c2"}), {"version": "0.4.0"}, "no release v0.4.0"),
        (FakeRepo(head="c3", tags={"v0.1.0": "c1"}, migrations={"c1": 4}), {"version": "v0.1.0"}, "0005_step.sql"),
        (FakeRepo(head="c2", upstream="c3", diverged=True), {"dev": True}, "both moved on"),
    ],
)
def test_update_stops_before_changing_anything(settings: Settings, repo: Path, fake: FakeRepo, options: dict, message: str):
    restarts: list[str] = []
    with pytest.raises(update.UpdateError, match=message):
        run_update(settings, repo, fake, restarts, **options)
    assert not any(command.startswith(("git switch", "git merge", "uv", "npm")) for command in fake.commands)
    assert (settings.web_dist / "index.html").read_text() == "old"
    assert restarts == []


def test_a_failed_build_leaves_the_running_app_alone(settings: Settings, repo: Path):
    restarts: list[str] = []
    with pytest.raises(update.UpdateError):
        run_update(settings, repo, FakeRepo(head="c1", tags={"v0.2.0": "c2"}, build_fails=True), restarts)
    assert (settings.web_dist / "index.html").read_text() == "old"
    assert restarts == []
