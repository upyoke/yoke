"""Native discovery, baseline-owned cleanup, and instruction suppression."""

from pathlib import Path

import pytest

from yoke_cli.project_install import instruction_discovery as instructions
from yoke_cli.project_install import skill_discovery as skills
from yoke_cli.project_install.files import ProjectInstallError, sha256_text
from yoke_contracts.project_contract.managed_block import render_block


def _skill(root: Path, rel: str, content: str = "# skill\n") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def test_fresh_discovery_link_and_repeated_refresh_share_one_source(tmp_path):
    canonical = _skill(tmp_path, ".agents/skills/yoke/onboard/SKILL.md")
    skills.preflight(tmp_path, {})
    assert skills.apply(tmp_path) == [".claude/skills/yoke"]
    native = tmp_path / ".claude/skills/yoke/onboard/SKILL.md"
    assert native.resolve() == canonical
    skills.preflight(tmp_path, {})
    assert skills.apply(tmp_path) == []
    canonical.write_text("updated canonical\n")
    assert native.read_text() == "updated canonical\n"
    assert not (tmp_path / ".codex/skills/yoke").exists()


def test_legacy_copy_requires_matching_manifest_baseline(tmp_path):
    duplicate = _skill(tmp_path, ".codex/skills/yoke/onboard/SKILL.md")
    prior = {
        "files": {
            str(duplicate.relative_to(tmp_path)): sha256_text(duplicate.read_text())
        }
    }
    skills.preflight(tmp_path, prior)
    duplicate.write_text("project modification\n")
    with pytest.raises(
        ProjectInstallError, match="skill_discovery_ownership_ambiguous"
    ):
        skills.preflight(tmp_path, prior)
    assert duplicate.read_text() == "project modification\n"


def test_equal_copies_do_not_prove_ownership_in_a_clone(tmp_path):
    _skill(tmp_path, ".agents/skills/yoke/onboard/SKILL.md")
    duplicate = _skill(tmp_path, ".claude/skills/yoke/onboard/SKILL.md")
    with pytest.raises(ProjectInstallError, match="missing ownership baseline"):
        skills.preflight(tmp_path, {})
    assert duplicate.exists()


def test_stale_alias_records_never_prune_the_canonical_target(tmp_path):
    canonical = _skill(tmp_path, ".agents/skills/yoke/SKILL.md")
    skills.apply(tmp_path)
    prior = {".claude/skills/yoke/SKILL.md": sha256_text(canonical.read_text())}
    assert skills.prune_records(tmp_path, prior) == {}
    assert canonical.exists()


def test_symlink_failure_names_native_recovery_before_cleanup(tmp_path, monkeypatch):
    def refused(*args, **kwargs):
        raise OSError("symlinks disabled")

    monkeypatch.setattr(Path, "symlink_to", refused)
    with pytest.raises(
        ProjectInstallError,
        match="skill_discovery_link_unavailable.*Windows Developer Mode",
    ):
        skills.preflight(tmp_path, {})
    assert list(tmp_path.iterdir()) == []


def test_discovery_uninstall_only_unlinks_its_recorded_entry(tmp_path):
    canonical = _skill(tmp_path, ".agents/skills/yoke/SKILL.md")
    skills.apply(tmp_path)
    assert skills.remove(tmp_path, skills.SKILL_DISCOVERY_LINKS) == [
        ".claude/skills/yoke"
    ]
    assert canonical.exists()


def test_instruction_retirement_preserves_project_content_byte_for_byte(tmp_path):
    block = render_block("shared rules")
    content = "# User preface\n\n" + block + "\n\n# User tail\n"
    path = _skill(tmp_path, "CODEX.md", content)
    prior = {
        "managed_markdown": {
            "CODEX.md": {"block_sha": sha256_text(block), "file_created": False}
        }
    }
    plan = instructions.retirement_plan(tmp_path, prior)
    assert instructions.apply_retirement(tmp_path, plan) == ["CODEX.md"]
    assert path.read_text() == content.replace(block, "")


def test_modified_instruction_block_refuses_and_keeps_bytes(tmp_path):
    path = _skill(tmp_path, "CLAUDE.md", render_block("modified"))
    prior = {
        "managed_markdown": {
            "CLAUDE.md": {"block_sha": sha256_text(render_block("old"))}
        }
    }
    with pytest.raises(ProjectInstallError, match="instruction_ownership_ambiguous"):
        instructions.retirement_plan(tmp_path, prior)
    assert "modified" in path.read_text()


def test_installer_created_empty_shell_is_removed(tmp_path):
    block = render_block("shared rules")
    _skill(tmp_path, "CLAUDE.md", block + "\n")
    prior = {
        "managed_markdown": {
            "CLAUDE.md": {"block_sha": sha256_text(block), "file_created": True}
        }
    }
    plan = instructions.retirement_plan(tmp_path, prior)
    assert plan == {"CLAUDE.md": None}
    instructions.assert_claude_loading(tmp_path, plan, settings={})
    instructions.apply_retirement(tmp_path, plan)
    assert not (tmp_path / "CLAUDE.md").exists()


@pytest.mark.parametrize("rel", ["CLAUDE.md", "CLAUDE.local.md", ".claude/CLAUDE.md"])
def test_ancestor_claude_files_refuse_default_loading(tmp_path, rel):
    root = tmp_path / "project"
    root.mkdir()
    user_file = _skill(tmp_path, rel, "# User-specific content\n")
    with pytest.raises(
        ProjectInstallError, match="canonical_instructions_not_loaded.*suppresses"
    ):
        instructions.assert_claude_loading(root, {}, settings={})
    settings = {
        "pluginConfigs": {
            "cc-plugin-agents-md@builtin": {
                "options": {"instructionFiles": "claude-md-and-agents-md"}
            }
        }
    }
    instructions.assert_claude_loading(root, {}, settings=settings)
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
    ],
)
def test_disabled_or_excluded_native_instructions_refuse(tmp_path, settings):
    with pytest.raises(ProjectInstallError, match="canonical_instructions_not_loaded"):
        instructions.assert_claude_loading(tmp_path, {}, settings=settings)


def test_native_claude_runtime_floor_refuses_older_engine(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(instructions.shutil, "which", lambda _: "/native/claude")
    monkeypatch.setattr(
        instructions.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout="2.1.280", returncode=0),
    )
    with pytest.raises(
        ProjectInstallError, match="instruction_runtime_unsupported.*2.1.281"
    ):
        instructions.preflight(tmp_path, {})


def test_user_owned_canonical_instruction_symlink_is_preserved(tmp_path):
    _skill(tmp_path, "AGENTS.md", render_block("canonical"))
    (tmp_path / "CLAUDE.md").symlink_to("AGENTS.md")
    assert instructions.retirement_plan(tmp_path, {}) == {}
    instructions.assert_claude_loading(tmp_path, {}, settings={})
    assert (tmp_path / "CLAUDE.md").is_symlink()
