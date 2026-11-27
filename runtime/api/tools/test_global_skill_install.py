"""The user-level ``yoke-global`` skill installs once and uninstall removes it.

One shared folder serves Codex and Cursor; Claude Code gets its own copy of
the skill in a real folder, never a link. Every created folder is recorded in the harness settings ledger, so
``revert_recorded`` (what ``yoke uninstall`` runs) removes them. A path Yoke
did not create is never overwritten.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from yoke_contracts import global_skill_install as install
from yoke_contracts import harness_settings_ledger as ledger
from yoke_contracts import platform_links as links
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


def test_install_places_the_shared_folder_and_a_claude_copy(home: Path) -> None:
    result = install.ensure_global_skill({"HOME": str(home)})

    assert not result.reason
    skill = _shared(home) / "SKILL.md"
    assert skill.read_text(encoding="utf-8") == install.skill_text()
    assert skill.read_text(encoding="utf-8").startswith("---\nname: yoke-global\n")
    copy = home / ".claude" / "skills" / "yoke-global"
    assert copy.is_dir() and not links.is_link(copy)
    assert (copy / "SKILL.md").read_text(encoding="utf-8") == install.skill_text()
    assert [(e["kind"], e["file"]) for e in ledger.read()] == [
        ("created_dir", str(_shared(home))),
        ("created_parent_dir", str(home / ".agents" / "skills")),
        ("created_parent_dir", str(home / ".agents")),
        ("created_dir", str(copy)),
        ("created_parent_dir", str(home / ".claude" / "skills")),
    ]
    assert any(line.startswith("codex: reads") for line in result.lines)


def test_second_install_is_a_no_op(home: Path) -> None:
    install.ensure_global_skill({"HOME": str(home)})
    before = ledger.read()
    result = install.ensure_global_skill({"HOME": str(home)})
    assert not result.reason and ledger.read() == before


def test_uninstall_removes_both_paths_and_the_empty_parents(home: Path) -> None:
    install.ensure_global_skill({"HOME": str(home)})
    lines, failures = revert_recorded()

    assert failures == []
    assert not (home / ".agents").exists()
    assert not (home / ".claude" / "skills").exists()
    assert (home / ".claude").is_dir()
    assert len(lines) == 5
    assert revert_recorded() == ([], [])


def test_uninstall_keeps_a_parent_that_gained_other_skills(home: Path) -> None:
    install.ensure_global_skill({"HOME": str(home)})
    other = home / ".agents" / "skills" / "someone-else"
    other.mkdir()

    lines, failures = revert_recorded()

    assert failures == []
    assert not _shared(home).exists() and other.is_dir()
    assert any(line.startswith("kept ") for line in lines)


def test_existing_parents_are_not_recorded(home: Path) -> None:
    (home / ".agents" / "skills").mkdir(parents=True)
    (home / ".claude" / "skills").mkdir()

    install.ensure_global_skill({"HOME": str(home)})

    assert {e["kind"] for e in ledger.read()} == {"created_dir"}


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
    (mine / "SKILL.md").write_text("the user's own skill\n", encoding="utf-8")

    result = install.ensure_global_skill({"HOME": str(home)})

    assert result.refused and result.reason == install.NOT_OWNED
    assert str(mine) in result.recovery and "harness-setup --fix" in result.recovery
    assert (mine / "SKILL.md").read_text(encoding="utf-8") == "the user's own skill\n"
    assert ledger.read() == []


def test_an_owned_older_copy_is_refreshed(home: Path) -> None:
    install.ensure_global_skill({"HOME": str(home)})
    (_shared(home) / "SKILL.md").write_text("older release text\n", encoding="utf-8")

    result = install.ensure_global_skill({"HOME": str(home)})

    assert not result.reason
    assert (_shared(home) / "SKILL.md").read_text(encoding="utf-8") == install.skill_text()


def test_a_claude_folder_yoke_did_not_create_is_refused(home: Path) -> None:
    folder = home / ".claude" / "skills" / "yoke-global"
    folder.mkdir(parents=True)

    result = install.ensure_global_skill({"HOME": str(home)})

    assert result.reason == install.NOT_OWNED and str(folder) in result.recovery
    assert folder.is_dir() and not any(folder.iterdir())


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
    assert global_skill_for_harness("claude-code").placement == "copy"
    with pytest.raises(KeyError, match="HARNESS_GLOBAL_SKILLS"):
        global_skill_for_harness("unknown-harness")


def test_skill_body_stays_within_the_teaching_ceiling() -> None:
    text = install.skill_text()
    assert len(text.splitlines()) <= 350
    assert "name: yoke-global" in text


DOCS_ROOT = Path(__file__).resolve().parents[3] / "docs" / "public"


def test_every_docs_link_in_the_skill_names_a_published_page() -> None:
    paths = re.findall(r"https://upyoke\.com/docs((?:/[\w.-]+)*)", install.skill_text())
    assert paths
    for path in paths:
        page = path.strip("/")
        assert (DOCS_ROOT / f"{page}.md").is_file() or (
            DOCS_ROOT / page / "index.md"
        ).is_file(), f"yoke-global links https://upyoke.com/docs{path}, not a page"


# The Claude placement is a real folder because a native Windows SSH session
# may refuse to traverse a junction (WinError 448, untrusted mount point). A
# link an earlier release recorded is replaced without following it; on
# Windows those links are junctions.

windows_smoke = pytest.mark.windows


def _claude_copy(home: Path) -> Path:
    return home / ".claude" / "skills" / "yoke-global"


def _deny_symlink(*args, **kwargs):
    raise PermissionError("symlink privilege unavailable")


def _native_link(target: Path, path: Path, monkeypatch) -> None:
    """A junction on Windows, a symlink elsewhere: what earlier releases placed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        with monkeypatch.context() as patch:
            patch.setattr(Path, "symlink_to", _deny_symlink)
            assert links.link(target, path) == "junction"
    else:
        assert links.link(target, path) == "symlink"


def _refuse_traversal(monkeypatch) -> None:
    def untrusted(*args, **kwargs):
        raise OSError(22, "untrusted mount point (WinError 448)")

    monkeypatch.setattr(Path, "resolve", untrusted)
    monkeypatch.setattr(os.path, "realpath", untrusted)


def _owned_link_from_an_earlier_release(home: Path, monkeypatch) -> Path:
    install.ensure_global_skill({"HOME": str(home)})
    copy = _claude_copy(home)
    (copy / "SKILL.md").unlink()
    copy.rmdir()
    _native_link(_shared(home), copy, monkeypatch)
    return copy


@windows_smoke
def test_an_owned_link_is_replaced_by_a_copy_without_traversing_it(
    home: Path, monkeypatch
) -> None:
    copy = _owned_link_from_an_earlier_release(home, monkeypatch)
    before = ledger.read()
    _refuse_traversal(monkeypatch)
    assert install.global_skill_ready("claude-code", {"HOME": str(home)}) == (
        False,
        f"global_skill_missing: {copy / 'SKILL.md'}",
    )

    result = install.ensure_global_skill({"HOME": str(home)})

    assert not result.reason and ledger.read() == before
    assert not links.is_link(copy) and copy.is_dir()
    assert (copy / "SKILL.md").read_text(encoding="utf-8") == install.skill_text()
    assert (_shared(home) / "SKILL.md").read_text(encoding="utf-8") == install.skill_text()
    assert install.global_skill_ready("claude-code", {"HOME": str(home)}) == (True, "")


@windows_smoke
def test_a_foreign_link_is_left_untouched(home: Path, tmp_path: Path, monkeypatch) -> None:
    copy = _claude_copy(home)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    _native_link(elsewhere, copy, monkeypatch)
    _refuse_traversal(monkeypatch)

    result = install.ensure_global_skill({"HOME": str(home)})

    assert result.reason == install.NOT_OWNED and str(copy) in result.recovery
    assert links.is_link(copy) and links.link_target(copy) == elsewhere.absolute()
    assert str(copy) not in {e["file"] for e in ledger.read()}


@windows_smoke
def test_uninstall_removes_an_owned_link_and_keeps_its_target(
    home: Path, monkeypatch
) -> None:
    copy = _owned_link_from_an_earlier_release(home, monkeypatch)

    lines, failures = revert_recorded()

    assert failures == [] and f"removed {copy}" in lines
    assert not os.path.lexists(copy) and not _shared(home).exists()


def test_a_stale_claude_copy_is_reported_then_refreshed(home: Path) -> None:
    install.ensure_global_skill({"HOME": str(home)})
    stale = _claude_copy(home) / "SKILL.md"
    stale.write_text("older release text\n", encoding="utf-8")
    assert install.global_skill_ready("claude-code", {"HOME": str(home)}) == (
        False,
        f"global_skill_missing: {stale}",
    )

    result = install.ensure_global_skill({"HOME": str(home)})

    assert not result.reason
    assert stale.read_text(encoding="utf-8") == install.skill_text()
    assert install.global_skill_ready("claude-code", {"HOME": str(home)}) == (True, "")
