"""Native discovery, baseline-owned cleanup, and instruction suppression."""

from pathlib import Path

import pytest

from yoke_cli.project_install import instruction_discovery as instructions
from yoke_cli.project_install import skill_discovery as skills
from yoke_cli.project_install.files import ProjectInstallError
from yoke_contracts.project_contract.managed_block import render_block


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


def test_symlink_failure_names_native_recovery_before_cleanup(tmp_path, monkeypatch):
    def refused(*args, **kwargs):
        raise OSError("symlinks disabled")

    monkeypatch.setattr(Path, "symlink_to", refused)
    with pytest.raises(
        ProjectInstallError,
        match="skill_discovery_link_unavailable.*Windows Developer Mode",
    ):
        skills.preflight(tmp_path)
    assert list(tmp_path.iterdir()) == []


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
