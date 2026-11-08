"""`fintrack update`: bring this checkout up to date with GitHub and restart the background service on it.

Every step must succeed before the next starts. The web app is built into a staging folder and only
swapped in once the build has finished, so a failed update leaves the running app as it was.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from . import service
from .config import REPO_ROOT, Settings

Run = Callable[[Sequence[str], Path], str]


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
    repo: Path = REPO_ROOT,
    run: Run = run_command,
    restart: Callable[[Settings], int] = restart_service,
    say: Callable[[str], None] = print,
) -> str:
    """Update the code, dependencies and web app, then restart the service. Returns the version now running."""

    def git(*args: str) -> str:
        return run(["git", *args], repo)

    if git("status", "--porcelain", "--untracked-files=no"):
        raise UpdateError("This checkout has uncommitted changes; commit or stash them first, so the update doesn't mix them in")
    before = git("rev-parse", "HEAD")

    say("Fetching from GitHub…")
    git("fetch", "--tags", "origin")
    if git("rev-list", "--count", "HEAD..@{upstream}") != "0":
        if git("rev-list", "--count", "@{upstream}..HEAD") != "0":
            raise UpdateError("This branch and GitHub have both moved on; merge or rebase by hand first")
        git("merge", "--ff-only", "@{upstream}")
    after = git("rev-parse", "HEAD")
    version = git("describe", "--tags", "--always", after)
    if after == before:
        say(f"Code: already up to date ({version})")
    else:
        say(f"Code: {git('describe', '--tags', '--always', before)} → {version}")

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
        return version
    say("Restarting the background service…")
    pid = restart(settings)
    say(f"Background service running (pid {pid})")
    return version


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
