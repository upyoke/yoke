"""Skill discovery tests for bootstrap.py.

Companion to ``test_bootstrap.py`` (which keeps the spec/render
coverage). Verifies ``list_skills`` / ``resolve_skill_path`` against a
fake ``.agents/skills/yoke`` tree and against the live repo checkout.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from runtime.harness.bootstrap import (
    ROOT_SKILL_NAME,
    SKILLS_ROOT_REL,
    list_skills,
    main,
    resolve_skill_path,
)


def _skill_frontmatter(skill_md: Path) -> dict[str, str]:
    content = skill_md.read_text(encoding="utf-8")
    if not content.startswith("---\n"):
        raise AssertionError(f"missing YAML frontmatter in {skill_md}")

    _, frontmatter, _ = content.split("---", 2)
    fields: dict[str, str] = {}
    for line in frontmatter.splitlines():
        stripped = line.strip()
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        fields[key] = value.strip().strip('"')
    return fields


@pytest.fixture
def skills_tree(tmp_path):
    """Build a fake ``.agents/skills/yoke`` tree with a compatibility alias.

    Layout mirrors the real repo: hidden ``.agents`` root with a top-level
    router ``SKILL.md``, a handful of named subskill directories (each with
    ``SKILL.md``), a ``scripts`` directory that is NOT a skill (no ``SKILL.md``),
    a nested phase file under ``advance/`` that must not surface as a skill,
    and a ``.claude/skills/yoke`` symlink pointing at the canonical tree.
    """
    agents_yoke = tmp_path / SKILLS_ROOT_REL
    agents_yoke.mkdir(parents=True)
    (agents_yoke / "SKILL.md").write_text("# yoke router\n")

    for name in ("idea", "strategize", "advance"):
        (agents_yoke / name).mkdir()
        (agents_yoke / name / "SKILL.md").write_text(f"# {name}\n")

    # Phase sub-file under advance/ — must not surface as a skill entry.
    (agents_yoke / "advance" / "preflight.md").write_text("# preflight\n")

    # scripts/ has no SKILL.md — must not surface either.
    (agents_yoke / "scripts").mkdir()
    (agents_yoke / "scripts" / "helper.py").write_text("# helper\n")

    # Compatibility symlink: .claude/skills/yoke → ../../.agents/skills/yoke.
    claude_skills = tmp_path / ".claude" / "skills"
    claude_skills.mkdir(parents=True)
    try:
        os.symlink(
            Path("..") / ".." / ".agents" / "skills" / "yoke",
            claude_skills / "yoke",
        )
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this filesystem")

    return tmp_path


class TestListSkills:
    def test_includes_root_router_and_subskills(self, skills_tree):
        result = list_skills(skills_tree)
        assert result[0] == ROOT_SKILL_NAME
        assert "idea" in result
        assert "strategize" in result
        assert "advance" in result

    def test_excludes_non_skill_directories(self, skills_tree):
        result = list_skills(skills_tree)
        # scripts/ has no SKILL.md and must not appear.
        assert "scripts" not in result

    def test_excludes_phase_sub_files(self, skills_tree):
        result = list_skills(skills_tree)
        # Phase sub-files like advance/preflight.md are not skills.
        assert "preflight" not in result
        assert "preflight.md" not in result

    def test_missing_tree_raises(self, tmp_path):
        # No .agents/skills/yoke at all.
        with pytest.raises(FileNotFoundError, match="Yoke skill root not found"):
            list_skills(tmp_path)


class TestResolveSkillPath:
    def test_root_skill_returns_top_level_skill_md(self, skills_tree):
        result = resolve_skill_path(skills_tree, "yoke")
        expected = skills_tree / SKILLS_ROOT_REL / "SKILL.md"
        assert Path(str(result)).resolve() == expected.resolve()

    def test_named_subskill_returns_canonical_path(self, skills_tree):
        result = resolve_skill_path(skills_tree, "strategize")
        expected = skills_tree / SKILLS_ROOT_REL / "strategize" / "SKILL.md"
        assert Path(str(result)).resolve() == expected.resolve()
        # Canonical form always lives under .agents/skills/yoke, never .claude.
        assert ".agents/skills/yoke" in str(result)
        assert ".claude/skills/yoke" not in str(result)

    def test_missing_skill_raises(self, skills_tree):
        with pytest.raises(FileNotFoundError, match="does-not-exist"):
            resolve_skill_path(skills_tree, "does-not-exist")

    def test_no_home_directory_fallback(self, skills_tree):
        """The resolver must not synthesize ~/.agents or ~/.codex paths."""
        # Even with a bogus name, the error message should reference the
        # repo-local .agents path, never a home-directory fallback.
        try:
            resolve_skill_path(skills_tree, "does-not-exist")
        except FileNotFoundError as exc:
            msg = str(exc)
            assert ".agents/skills/yoke" in msg
            assert "~/.agents" not in msg
            assert "~/.codex" not in msg
            assert os.path.expanduser("~") not in msg


class TestSkillCompatibilitySymlink:
    """AC-4: .claude/skills/yoke is a compatibility alias to the canonical tree."""

    def test_compat_symlink_resolves_to_same_target(self, skills_tree):
        canonical = (skills_tree / SKILLS_ROOT_REL / "strategize" / "SKILL.md").resolve()
        compat = (
            skills_tree / ".claude" / "skills" / "yoke" / "strategize" / "SKILL.md"
        ).resolve()
        assert canonical == compat

    def test_resolver_returns_canonical_not_compat_path(self, skills_tree):
        """Resolver must never return the .claude/... alias."""
        result = str(resolve_skill_path(skills_tree, "idea"))
        assert ".agents/skills/yoke" in result
        assert "/.claude/skills/yoke" not in result


class TestSkillCLI:
    def test_skill_list_cli(self, skills_tree, capsys):
        main(["skill-list", "--root", str(skills_tree)])
        out = capsys.readouterr().out
        lines = [line for line in out.splitlines() if line]
        assert lines[0] == ROOT_SKILL_NAME
        assert "strategize" in lines
        assert "idea" in lines
        assert "scripts" not in lines

    def test_skill_path_cli_resolves_named_skill(self, skills_tree, capsys):
        main(["skill-path", "strategize", "--root", str(skills_tree)])
        out = capsys.readouterr().out.strip()
        assert out.endswith(".agents/skills/yoke/strategize/SKILL.md")

    def test_skill_path_cli_resolves_root_skill(self, skills_tree, capsys):
        main(["skill-path", "yoke", "--root", str(skills_tree)])
        out = capsys.readouterr().out.strip()
        assert out.endswith(".agents/skills/yoke/SKILL.md")

    def test_skill_path_cli_missing_exits_nonzero(self, skills_tree, capsys):
        with pytest.raises(SystemExit) as exc_info:
            main(["skill-path", "does-not-exist", "--root", str(skills_tree)])
        assert exc_info.value.code == 2
        err = capsys.readouterr().err
        assert "does-not-exist" in err
        # No home-directory fallback mentioned in stderr either.
        assert "~/.agents" not in err

    def test_skill_path_cli_requires_name(self, skills_tree):
        with pytest.raises(SystemExit) as exc_info:
            main(["skill-path", "--root", str(skills_tree)])
        assert exc_info.value.code == 1

    def test_skill_list_cli_does_not_require_spec(self, skills_tree, capsys):
        """skill-list must work without --spec (regression guard)."""
        main(["skill-list", "--root", str(skills_tree)])
        out = capsys.readouterr().out
        assert ROOT_SKILL_NAME in out.splitlines()


class TestSkillRealRepoDiscovery:
    """AC-1, AC-2: verify discovery against the real repo checkout."""

    @pytest.fixture
    def repo_root(self):
        # Walk up from this file to find the repo root (directory containing
        # both ``.agents/skills/yoke`` and ``yoke/api``).
        here = Path(__file__).resolve()
        for candidate in [here, *here.parents]:
            if (candidate / SKILLS_ROOT_REL / "SKILL.md").is_file():
                return candidate
        pytest.skip("Real .agents/skills/yoke tree not available in this checkout")

    def test_real_tree_lists_expected_skills(self, repo_root):
        result = list_skills(repo_root)
        # Must include yoke, idea, and strategize.
        assert ROOT_SKILL_NAME in result
        assert "idea" in result
        assert "strategize" in result

    def test_real_tree_strategize_resolves(self, repo_root):
        # Strategize must resolve to the canonical .agents/... path.
        path = resolve_skill_path(repo_root, "strategize")
        assert str(path).endswith(".agents/skills/yoke/strategize/SKILL.md")

    def test_codex_visible_yoke_skills_use_shared_frontmatter(self, repo_root):
        """Codex scans nested SKILL.md files, so SKILL.md is the shared metadata source."""
        skill_files = sorted((repo_root / SKILLS_ROOT_REL).rglob("SKILL.md"))
        assert skill_files
        for skill_md in skill_files:
            fields = _skill_frontmatter(skill_md)
            assert fields.get("name")
            assert fields.get("description")

    def test_yoke_skills_do_not_duplicate_codex_metadata(self, repo_root):
        """Yoke keeps Claude and Codex on the same SKILL.md source by default."""
        sidecars = sorted((repo_root / SKILLS_ROOT_REL).rglob("agents/openai.yaml"))
        assert sidecars == []
