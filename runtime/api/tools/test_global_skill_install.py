"""The user-level ``yoke-global`` skill installs once and uninstall removes it.

One shared folder serves Codex and Cursor; Claude Code gets a symlink to it.
Every created folder and link is recorded in the harness settings ledger, so
``revert_recorded`` (what ``yoke uninstall`` runs) removes them. A path Yoke
did not create is never overwritten.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_contracts import global_skill_install as install
from yoke_contracts import harness_settings_ledger as ledger
from yoke_contracts.harness_global_skill import (
    HARNESS_GLOBAL_SKILLS,
    global_skill_for_harness,
)
from yoke_contracts.harness_settings_revert import revert_recorded


@pytest.fixture()
def home(tmp_path: Path) -> Path:
    root = tmp_path / "home"
    for name in (".claude", ".codex", ".cursor"):
        (root / name).mkdir(parents=True)
    return root


def _shared(home: Path) -> Path:
    return home / ".agents" / "skills" / "yoke-global"


def test_install_places_one_copy_and_a_claude_link(home: Path) -> None:
    result = install.ensure_global_skill({"HOME": str(home)})

    assert not result.reason
    skill = _shared(home) / "SKILL.md"
    assert skill.read_text() == install.skill_text()
    assert skill.read_text().startswith("---\nname: yoke-global\n")
    link = home / ".claude" / "skills" / "yoke-global"
    assert link.is_symlink() and link.resolve() == _shared(home).resolve()
    assert sorted(e["file"] for e in ledger.read()) == sorted(
        [str(_shared(home)), str(link)]
    )
    assert any(line.startswith("codex: reads") for line in result.lines)


def test_second_install_is_a_no_op(home: Path) -> None:
    install.ensure_global_skill({"HOME": str(home)})
    before = ledger.read()
    result = install.ensure_global_skill({"HOME": str(home)})
    assert not result.reason and ledger.read() == before


def test_uninstall_removes_both_paths(home: Path) -> None:
    install.ensure_global_skill({"HOME": str(home)})
    lines, failures = revert_recorded()

    assert failures == []
    assert not _shared(home).exists()
    assert not (home / ".claude" / "skills" / "yoke-global").is_symlink()
    assert (home / ".claude").is_dir()
    assert len(lines) == 2
    assert revert_recorded() == ([], [])


def test_absent_harness_home_is_skipped_never_created(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("CODEX_HOME", raising=False)
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)

    result = install.ensure_global_skill({"HOME": str(home)})

    assert (_shared(home) / "SKILL.md").is_file()
    assert not (home / ".claude").exists() and not (home / ".cursor").exists()
    assert "claude-code: not installed; skipped" in result.lines


def test_no_harness_installs_nothing(tmp_path: Path) -> None:
    result = install.ensure_global_skill({"HOME": str(tmp_path)})

    assert result.reason == install.NO_HARNESS and not result.refused
    assert not (tmp_path / ".agents").exists()


def test_a_folder_yoke_did_not_create_is_refused(home: Path) -> None:
    mine = _shared(home)
    mine.mkdir(parents=True)
    (mine / "SKILL.md").write_text("the user's own skill\n")

    result = install.ensure_global_skill({"HOME": str(home)})

    assert result.refused and result.reason == install.NOT_OWNED
    assert str(mine) in result.recovery and "yoke setup" in result.recovery
    assert (mine / "SKILL.md").read_text() == "the user's own skill\n"
    assert ledger.read() == []


def test_an_owned_older_copy_is_refreshed(home: Path) -> None:
    install.ensure_global_skill({"HOME": str(home)})
    (_shared(home) / "SKILL.md").write_text("older release text\n")

    result = install.ensure_global_skill({"HOME": str(home)})

    assert not result.reason
    assert (_shared(home) / "SKILL.md").read_text() == install.skill_text()


def test_a_claude_link_yoke_did_not_create_is_refused(home: Path) -> None:
    link = home / ".claude" / "skills" / "yoke-global"
    link.mkdir(parents=True)

    result = install.ensure_global_skill({"HOME": str(home)})

    assert result.reason == install.NOT_OWNED and str(link) in result.recovery
    assert link.is_dir() and not link.is_symlink()


def test_codex_home_override_decides_installation(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / "codex-elsewhere").mkdir()
    environ = {"HOME": str(home), "CODEX_HOME": str(tmp_path / "codex-elsewhere")}

    result = install.ensure_global_skill(environ)

    assert (_shared(home) / "SKILL.md").is_file()
    assert any(line.startswith("codex: reads") for line in result.lines)


def test_contract_covers_every_manifest_harness() -> None:
    assert set(HARNESS_GLOBAL_SKILLS) == {"claude-code", "codex", "cursor"}
    assert global_skill_for_harness("claude-code").placement == "link"
    with pytest.raises(KeyError, match="HARNESS_GLOBAL_SKILLS"):
        global_skill_for_harness("unknown-harness")


def test_skill_body_stays_within_the_teaching_ceiling() -> None:
    text = install.skill_text()
    assert len(text.splitlines()) <= 350
    assert "name: yoke-global" in text and "yoke setup --agent" in text
