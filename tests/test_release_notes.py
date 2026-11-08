from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release_notes.py"
spec = importlib.util.spec_from_file_location("release_notes", SCRIPT)
release_notes = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
spec.loader.exec_module(release_notes)  # type: ignore[union-attr]

CHANGELOG = """# Changelog

## Unreleased

- Something new

## 0.2.0-rc.1 - 2026-12-01

- A candidate

## 0.1.0 - 2026-11-07

- The first release
"""


def project(tmp_path: Path, python_version: str, npm_version: str, chinese: str | None = None) -> Path:
    (tmp_path / "web").mkdir()
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "fintrack"\nversion = "{python_version}"\n')
    (tmp_path / "web" / "package.json").write_text(json.dumps({"name": "fintrack-web", "version": npm_version}))
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG)
    if chinese is not None:
        (tmp_path / "CHANGELOG.zh-CN.md").write_text(chinese)
    return tmp_path


def test_notes_are_the_tags_changelog_section_with_the_chinese_one_after(tmp_path: Path):
    root = project(tmp_path, "0.1.0", "0.1.0", chinese="# 更新日志\n\n## 0.1.0 - 2026-11-07\n\n- 第一个版本\n")
    assert release_notes.notes("v0.1.0", root) == "- The first release\n\n---\n\n## 中文说明\n\n- 第一个版本\n"


def test_a_pre_release_matches_pythons_spelling_of_its_version(tmp_path: Path):
    root = project(tmp_path, "0.2.0rc1", "0.2.0-rc.1")
    assert release_notes.notes("v0.2.0-rc.1", root) == "- A candidate\n"


@pytest.mark.parametrize(
    ("tag", "python_version", "npm_version", "message"),
    [
        ("v0.1.0", "0.1.0", "0.0.9", "web/package.json says version 0.0.9"),
        ("v0.1.0", "0.2.0", "0.1.0", "pyproject.toml says version 0.2.0"),
        ("v0.3.0", "0.3.0", "0.3.0", "no section for 0.3.0"),
        ("release-1", "0.1.0", "0.1.0", "isn't a release tag"),
    ],
)
def test_a_tag_that_doesnt_match_the_project_is_refused(tmp_path: Path, tag: str, python_version: str, npm_version: str, message: str):
    with pytest.raises(release_notes.ReleaseError, match=message):
        release_notes.notes(tag, project(tmp_path, python_version, npm_version))


def test_the_changelog_has_notes_for_the_version_the_project_declares():
    version = json.loads((release_notes.ROOT / "web" / "package.json").read_text())["version"]
    assert release_notes.notes(f"v{version}").strip()
