"""Run the server as a macOS LaunchAgent: starts at login, restarts if it crashes."""

from __future__ import annotations

import os
import plistlib
import subprocess
import time
from pathlib import Path

from .config import REPO_ROOT, Settings

LABEL = "com.fintrack.server"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


class ServiceError(RuntimeError):
    pass


def _domain() -> str:
    return f"gui/{os.getuid()}"


def agent_plist(settings: Settings) -> dict:
    log_path = settings.data_dir / "logs" / "server.log"
    return {
        "Label": LABEL,
        # The project's own virtualenv entry point, so the agent needs neither uv nor a shell.
        "ProgramArguments": [str(REPO_ROOT / ".venv" / "bin" / "fintrack"), "serve"],
        "WorkingDirectory": str(REPO_ROOT),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(log_path),
        "StandardErrorPath": str(log_path),
    }


def install(settings: Settings) -> Path:
    if not (settings.web_dist / "index.html").exists():
        raise ServiceError("The web app isn't built yet: run `npm --prefix web install` and `npm --prefix web run build` first")
    plist = agent_plist(settings)
    Path(plist["StandardOutPath"]).parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_bytes(plistlib.dumps(plist))
    # Replace a previously loaded copy, if any, so a reinstall picks up changes. bootout returns before the
    # old server has exited, and bootstrapping before then fails with "5: Input/output error".
    subprocess.run(["launchctl", "bootout", f"{_domain()}/{LABEL}"], capture_output=True, check=False)
    deadline = time.monotonic() + 10
    while _loaded() and time.monotonic() < deadline:
        time.sleep(0.2)
    result = subprocess.run(["launchctl", "bootstrap", _domain(), str(PLIST_PATH)], capture_output=True, text=True)
    if result.returncode != 0:
        raise ServiceError(f"launchctl bootstrap failed: {result.stderr.strip()}")
    return PLIST_PATH


def _loaded() -> bool:
    return subprocess.run(["launchctl", "print", f"{_domain()}/{LABEL}"], capture_output=True).returncode == 0


def uninstall() -> None:
    subprocess.run(["launchctl", "bootout", f"{_domain()}/{LABEL}"], capture_output=True, check=False)
    PLIST_PATH.unlink(missing_ok=True)


def status() -> str:
    result = subprocess.run(["launchctl", "print", f"{_domain()}/{LABEL}"], capture_output=True, text=True)
    if result.returncode != 0:
        return "not installed"
    fields = dict(
        line.strip().split(" = ", 1) for line in result.stdout.splitlines() if line.strip().startswith(("state = ", "pid = "))
    )
    return f"{fields.get('state', 'unknown')}" + (f" (pid {fields['pid']})" if "pid" in fields else "")
