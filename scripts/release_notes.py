"""Check a release tag against the project's version numbers and print the release notes for it.

Run by .github/workflows/release.yml when a tag is pushed:

    python3 scripts/release_notes.py v0.2.0 > notes.md

The tag has to match the versions in pyproject.toml and web/package.json, and CHANGELOG.md needs a
section for it; the matching section of CHANGELOG.zh-CN.md, if there is one, follows in Chinese.
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAG = re.compile(r"^v(\d+\.\d+\.\d+)(?:-(alpha|beta|rc)\.(\d+))?$")
PYTHON_PRE = {"alpha": "a", "beta": "b", "rc": "rc"}  # 1.2.0-rc.1 is written 1.2.0rc1 in Python


class ReleaseError(Exception):
    pass


def section(changelog: str, version: str) -> str | None:
    """The body under a "## 1.2.0" (or "## [1.2.0] - date") heading, up to the next heading of that level."""
    heading = re.compile(rf"^## \[?{re.escape(version)}\]?(?:\s.*)?$", re.M)
    match = heading.search(changelog)
    if match is None:
        return None
    rest = changelog[match.end() :]
    following = re.search(r"^## ", rest, re.M)
    return (rest[: following.start()] if following else rest).strip()


def notes(tag: str, root: Path = ROOT) -> str:
    match = TAG.match(tag)
    if match is None:
        raise ReleaseError(f"{tag} isn't a release tag: use v1.2.3, or v1.2.3-rc.1 for a pre-release")
    core, pre, number = match.groups()
    version = tag[1:]
    python_version = core + (f"{PYTHON_PRE[pre]}{number}" if pre else "")

    declared = {
        "pyproject.toml": (tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"], python_version),
        "web/package.json": (json.loads((root / "web" / "package.json").read_text())["version"], version),
    }
    for path, (found, wanted) in declared.items():
        if found != wanted:
            raise ReleaseError(f"{path} says version {found}, but the tag {tag} needs {wanted}")

    english = section((root / "CHANGELOG.md").read_text(), version)
    if not english:
        raise ReleaseError(f"CHANGELOG.md has no section for {version}: rename its Unreleased heading to {version}")
    chinese_path = root / "CHANGELOG.zh-CN.md"
    chinese = section(chinese_path.read_text(), version) if chinese_path.exists() else None
    return english + (f"\n\n---\n\n## 中文说明\n\n{chinese}" if chinese else "") + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        print(notes(argv[1]), end="")
    except ReleaseError as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
