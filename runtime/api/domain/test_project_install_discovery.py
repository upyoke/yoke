"""Native discovery, baseline-owned cleanup, and instruction suppression."""

import os
from pathlib import Path

import pytest

from yoke_cli.project_install import instruction_discovery as instructions
from yoke_cli.project_install import skill_discovery as skills
from yoke_cli.project_install.files import ProjectInstallError
from yoke_contracts.project_contract.managed_block import render_block

pytestmark = pytest.mark.windows


def _skill(root: Path, rel: str, content: str = "# skill\n") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def test_fresh_discovery_link_and_repeated_refresh_share_one_source(tmp_path):
    canonical = _skill(tmp_path, ".agents/skills/yoke/onboard/SKILL.md")
    skills.preflight(tmp_path)
    assert skills.apply(tmp_path) == [".claude/skills/yoke"]
    native = tmp_path / ".claude/skills/yoke/onboard/SKILL.md"
    assert native.resolve() == canonical
    skills.preflight(tmp_path)
    assert skills.apply(tmp_path) == []
    canonical.write_text("updated canonical\n")
    assert native.read_text() == "updated canonical\n"
    assert not (tmp_path / ".codex/skills/yoke").exists()


def test_link_failure_names_native_recovery(tmp_path, monkeypatch):
    _skill(tmp_path, ".agents/skills/yoke/SKILL.md")

    def refused(*args, **kwargs):
        raise OSError("link_creation_failed: enable Windows Developer Mode")

    monkeypatch.setattr(skills, "link", refused)
    with pytest.raises(
        ProjectInstallError,
        match="skill_discovery_link_unavailable.*Windows Developer Mode",
    ):
        skills.apply(tmp_path)
    assert not os.path.lexists(tmp_path / ".claude/skills/yoke")


def test_missing_skill_tree_is_a_named_refusal(tmp_path):
    with pytest.raises(ProjectInstallError, match="skill_discovery_target_missing"):
        skills.apply(tmp_path)


def test_git_placeholder_for_committed_link_is_replaced(tmp_path):
    _skill(tmp_path, ".agents/skills/yoke/SKILL.md")
    placeholder = tmp_path / ".claude/skills/yoke"
    placeholder.parent.mkdir(parents=True)
    placeholder.write_text("../../.agents/skills/yoke", encoding="utf-8")

    skills.preflight(tmp_path)
    assert skills.apply(tmp_path) == [".claude/skills/yoke"]
    assert skills.entry_state(tmp_path, ".claude/skills/yoke") == skills.LINKED


def test_recorded_copy_is_refreshed_and_unrecorded_directory_refused(tmp_path):
    _skill(tmp_path, ".agents/skills/yoke/SKILL.md")
    copy = tmp_path / ".claude/skills/yoke"
    copy.mkdir(parents=True)
    (copy / "SKILL.md").write_text("stale\n", encoding="utf-8")

    with pytest.raises(ProjectInstallError, match="skill_discovery_entry_conflict"):
        skills.preflight(tmp_path)
    records = dict(skills.SKILL_DISCOVERY_LINKS)
    skills.preflight(tmp_path, records)
    assert skills.apply(tmp_path, records) == [".claude/skills/yoke"]
    assert skills.entry_state(tmp_path, ".claude/skills/yoke") == skills.LINKED


def test_install_ignores_the_local_entry_and_uninstall_removes_the_line(tmp_path):
    _skill(tmp_path, ".agents/skills/yoke/SKILL.md")
    (tmp_path / ".gitignore").write_text("dist/\n", encoding="utf-8")

    assert skills.ignore(tmp_path) == ["/.claude/skills/yoke"]
    assert skills.ignore(tmp_path) == []
    skills.apply(tmp_path)
    skills.remove(tmp_path, skills.SKILL_DISCOVERY_LINKS)
    assert skills.unignore(tmp_path, skills.SKILL_DISCOVERY_LINKS) == [
        "/.claude/skills/yoke"
    ]

    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == "dist/\n"


def test_discovery_uninstall_only_unlinks_its_recorded_entry(tmp_path):
    canonical = _skill(tmp_path, ".agents/skills/yoke/SKILL.md")
    skills.apply(tmp_path)
    assert skills.remove(tmp_path, skills.SKILL_DISCOVERY_LINKS) == [
        ".claude/skills/yoke"
    ]
    assert canonical.exists()


@pytest.mark.parametrize("rel", ["CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md"])
def test_ancestor_claude_files_refuse_default_loading(tmp_path, rel):
    root = tmp_path / "project"
    root.mkdir()
    user_file = _skill(tmp_path, rel, "# User-specific content\n")
    with pytest.raises(
        ProjectInstallError, match="canonical_instructions_not_loaded.*suppresses"
    ):
        instructions.assert_claude_loading(root, settings={})
    settings = {
        "pluginConfigs": {
            "cc-plugin-agents-md@builtin": {
                "options": {"instructionFiles": "claude-md-and-agents-md"}
            }
        }
    }
    instructions.assert_claude_loading(root, settings=settings)
    assert user_file.read_text() == "# User-specific content\n"


@pytest.mark.parametrize(
    "settings",
    [
        {"enabledPlugins": {"cc-plugin-agents-md@builtin": False}},
        {
            "pluginConfigs": {
                "agents-md@builtin": {"options": {"instructionFiles": "claude-md"}}
            }
        },
        {
            "pluginConfigs": {
                "cc-plugin-agents-md@builtin": {
                    "options": {"instructionFiles": "managed-only"}
                }
            }
        },
        {"claudeMdExcludes": ["**/AGENTS.md"]},
        {
            "pluginConfigs": {
                "cc-plugin-agents-md@builtin": {"options": {"instructionFiles": []}}
            }
        },
    ],
)
def test_disabled_or_excluded_native_instructions_refuse(tmp_path, settings):
    with pytest.raises(ProjectInstallError, match="canonical_instructions_not_loaded"):
        instructions.assert_claude_loading(tmp_path, settings=settings)


def test_native_claude_runtime_floor_warns_for_older_engine(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        instructions.shutil,
        "which",
        lambda name: "/native/claude" if name == "claude" else None,
    )
    monkeypatch.setattr(
        instructions.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout="2.1.280", returncode=0),
    )
    health = instructions.preflight(tmp_path)
    claude = next(row for row in health if row["harness"] == "claude-code")
    assert claude["status"] == "below_floor"
    assert claude["floor"] == "2.1.281"


def test_user_owned_canonical_instruction_symlink_is_preserved(tmp_path):
    _skill(tmp_path, "AGENTS.md", render_block("canonical"))
    (tmp_path / "CLAUDE.md").symlink_to("AGENTS.md")
    instructions.assert_claude_loading(tmp_path, settings={})
    assert (tmp_path / "CLAUDE.md").is_symlink()


def test_codex_override_refuses_before_project_mutation(tmp_path, monkeypatch):
    override = _skill(tmp_path, "AGENTS.override.md", "User override\n")
    with pytest.raises(ProjectInstallError, match="AGENTS.override.md suppresses"):
        instructions.preflight(tmp_path)
    assert override.read_text() == "User override\n"
