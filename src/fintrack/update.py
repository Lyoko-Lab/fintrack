"""`fintrack update`: move this checkout to a release (or the latest code) and restart the background service on it.

By default it goes to the latest stable release, a tag like v1.2.3; a tag with a suffix (v1.3.0-rc.1) is a
pre-release and is only used when asked for by name. `--dev` follows the branch instead, for development.

Every step must succeed before the next starts. The web app is built into a staging folder and only
swapped in once the build has finished, so a failed update leaves the running app as it was.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from . import service
from .config import REPO_ROOT, Settings

Run = Callable[[Sequence[str], Path], str]

STABLE_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
MIGRATIONS = "src/fintrack/migrations/"


class UpdateError(RuntimeError):
    pass


def run_command(command: Sequence[str], cwd: Path) -> str:
    """Run a command and return what it printed; a failure raises UpdateError with the end of its output."""
    result = subprocess.run(list(command), cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-15:])
        raise UpdateError(f"`{' '.join(command)}` failed:\n{tail}")
    return result.stdout.strip()


def restart_service(settings: Settings) -> int:
    service.install(settings)
    return service.wait_until_running(settings)


def update(
    settings: Settings,
    *,
    version: str | None = None,
    dev: bool = False,
    repo: Path = REPO_ROOT,
    run: Run = run_command,
    restart: Callable[[Settings], int] = restart_service,
    say: Callable[[str], None] = print,
) -> str:
    """Update the code, dependencies and web app, then restart the service. Returns the version now running.

    `version` picks a release ("1.2.0" or "v1.2.0"); `dev` follows the branch's latest commits instead;
    with neither, the latest stable release.
    """

    def git(*args: str) -> str:
        return run(["git", *args], repo)

    if git("status", "--porcelain", "--untracked-files=no"):
        raise UpdateError("This checkout has uncommitted changes; commit or stash them first, so the update doesn't mix them in")
    before = git("rev-parse", "HEAD")

    say("Fetching from GitHub…")
    git("fetch", "--tags", "origin")
    if dev:
        _follow_branch(git, say)
    else:
        tag = _release_tag(git, version) if version else _latest_stable(git)
        if before != git("rev-parse", f"{tag}^{{commit}}"):
            _check_migrations(git, tag)
            git("switch", "--detach", tag)
    after = git("rev-parse", "HEAD")
    running = git("describe", "--tags", "--always", after)
    if after == before:
        say(f"Code: already at {running}")
    else:
        say(f"Code: {git('describe', '--tags', '--always', before)} → {running}")

    say("Installing Python dependencies…")
    run([_tool("uv"), "sync", "--locked"], repo)

    web = repo / "web"
    npm = _tool("npm")
    lock_changed = after != before and bool(git("diff", "--name-only", before, after, "--", "web/package-lock.json"))
    if lock_changed or not (web / "node_modules").exists():
        say("Installing web dependencies…")
        run([npm, "ci"], web)

    say("Building the web app…")
    run([npm, "run", "typecheck"], web)
    staging = settings.web_dist.with_name(f"{settings.web_dist.name}.next")
    shutil.rmtree(staging, ignore_errors=True)
    run([npm, "exec", "--", "vite", "build", "--outDir", str(staging), "--emptyOutDir"], web)
    _swap(staging, settings.web_dist)

    if not service.installed():
        say("The background service isn't installed, so there's nothing to restart: run `uv run fintrack service install`")
        return running
    say("Restarting the background service…")
    pid = restart(settings)
    say(f"Background service running (pid {pid})")
    return running


def _follow_branch(git: Callable[..., str], say: Callable[[str], None]) -> None:
    """Fast-forward to the branch on GitHub; commits made here and not pushed yet are kept and deployed."""
    if git("rev-parse", "--abbrev-ref", "HEAD") == "HEAD":
        say("Switching from the release back to the main branch…")
        git("switch", "main")
    if git("rev-list", "--count", "HEAD..@{upstream}") != "0":
        if git("rev-list", "--count", "@{upstream}..HEAD") != "0":
            raise UpdateError("This branch and GitHub have both moved on; merge or rebase by hand first")
        git("merge", "--ff-only", "@{upstream}")


def _release_tag(git: Callable[..., str], version: str) -> str:
    tag = version if version.startswith("v") else f"v{version}"
    if tag not in git("tag", "--list", tag).splitlines():
        raise UpdateError(f"There's no release {tag}; the releases are listed at https://github.com/Lyoko-Lab/fintrack/releases")
    return tag


def _latest_stable(git: Callable[..., str]) -> str:
    tags = [tag for tag in git("tag", "--list", "v*").splitlines() if STABLE_TAG.match(tag)]
    if not tags:
        raise UpdateError("There's no stable release yet; `fintrack update --dev` follows the latest code instead")
    latest = max(tags, key=lambda tag: tuple(int(part) for part in STABLE_TAG.match(tag).groups()))  # type: ignore[union-attr]
    # Code that is newer than the release (a development version) isn't rolled back without asking.
    if git("rev-list", "--count", f"{latest}..HEAD") != "0" and git("rev-list", "--count", f"HEAD..{latest}") == "0":
        raise UpdateError(
            f"This checkout is a development version, newer than the latest release {latest}. "
            f"Run `fintrack update --dev` to keep following the latest code, or `fintrack update {latest[1:]}` to go back to the release"
        )
    return latest


def _check_migrations(git: Callable[..., str], tag: str) -> None:
    """Refuse a version that lacks a migration this checkout has: the database may already be past it."""
    def migrations(rev: str) -> set[str]:
        return {Path(name).name for name in git("ls-tree", "--name-only", rev, MIGRATIONS).splitlines() if name.endswith(".sql")}

    missing = sorted(migrations("HEAD") - migrations(tag))
    if missing:
        raise UpdateError(
            f"{tag} is older than this checkout's database changes ({', '.join(missing)}), so it can't run on your data; "
            "pick a newer version"
        )


def _tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise UpdateError(f"`{name}` isn't on the PATH; see the Setup section of README.md")
    return path


def _swap(new: Path, current: Path) -> None:
    """Put the freshly built app where the server reads it, keeping the old one until the new one is in place."""
    if not (new / "index.html").exists():
        raise UpdateError(f"The web app build left no index.html in {new}")
    old = current.with_name(f"{current.name}.old")
    shutil.rmtree(old, ignore_errors=True)
    if current.exists():
        current.rename(old)
    new.rename(current)
    shutil.rmtree(old, ignore_errors=True)
