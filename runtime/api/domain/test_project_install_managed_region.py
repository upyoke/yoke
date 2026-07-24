"""End-to-end managed-region install: rules blocks + settings permissions.

Exercises the full bundle_apply / uninstall wiring with a synthetic bundle
carrying the ``managed_markdown`` and ``claude_settings_permissions`` keys.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import project_install
from yoke_core.domain.project_install import apply_bundle
from yoke_core.domain.project_install_test_helpers import make_bundle
from yoke_cli.project_install.managed_markdown import MANAGED_BLOCK_BEGIN

MANIFEST_REL = ".yoke/install-manifest.json"


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    return root


def _manifest(repo) -> dict:
    return json.loads((repo / MANIFEST_REL).read_text(encoding="utf-8"))


def _settings(repo) -> dict:
    return json.loads(
        (repo / ".claude/settings.json").read_text(encoding="utf-8")
    )


def _bundle() -> dict:
    bundle = make_bundle()
    bundle["managed_markdown"] = {
        "blocks": {
            "doctrine": "# Yoke doctrine\n\nWorktree discipline etc.",
            "codex_shell": "# Codex shell\n\nSee AGENTS.md.",
        },
        "targets": [
            {"path": "AGENTS.md", "block": "doctrine"},
            {"path": "CLAUDE.md", "block": "doctrine"},
            {"path": "CODEX.md", "block": "codex_shell"},
        ],
    }
    bundle["claude_settings_permissions"] = {
        "allow": ["Bash", "Write(**)", "Edit(**)", "Read(*)", "Monitor"],
        "auto_memory_enabled": False,
    }
    return bundle


def test_install_creates_rules_and_permissions(repo) -> None:
    report = apply_bundle(repo, _bundle(), source="test")

    for rel in ("AGENTS.md", "CLAUDE.md", "CODEX.md"):
        assert MANAGED_BLOCK_BEGIN in (repo / rel).read_text(encoding="utf-8")
    assert "Yoke doctrine" in (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert "Codex shell" in (repo / "CODEX.md").read_text(encoding="utf-8")

    settings = _settings(repo)
    assert "Monitor" in settings["permissions"]["allow"]
    assert settings["autoMemoryEnabled"] is False
    assert "hooks" in settings  # hook subtree co-managed, untouched

    man = _manifest(repo)
    assert set(man["managed_markdown"]) == {"AGENTS.md", "CLAUDE.md", "CODEX.md"}
    assert man["managed_markdown"]["AGENTS.md"]["file_created"] is True
    assert "Monitor" in man["settings_permissions"]["added_allow"]

    assert any(
        "Created: AGENTS.md" in line for line in report["managed_markdown_actions"]
    )
    assert report["settings_permissions_actions"]


def test_refresh_is_idempotent(repo) -> None:
    apply_bundle(repo, _bundle(), source="test")
    report = apply_bundle(repo, _bundle(), operation="refresh", source="test")
    assert report["managed_markdown_written"] == []


def test_preexisting_file_preserved_and_uninstall(repo) -> None:
    (repo / "AGENTS.md").write_text(
        "# Platform rules\n\nkeep me\n", encoding="utf-8"
    )
    apply_bundle(repo, _bundle(), source="test")

    agents = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert "keep me" in agents  # project content preserved
    assert MANAGED_BLOCK_BEGIN in agents  # block inserted
    assert _manifest(repo)["managed_markdown"]["AGENTS.md"]["file_created"] is False

    project_install.uninstall(repo)
    # AGENTS.md pre-existed -> kept, block stripped, project content intact
    assert (repo / "AGENTS.md").exists()
    after = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert "keep me" in after
    assert MANAGED_BLOCK_BEGIN not in after
    # CLAUDE.md / CODEX.md were installer-created -> removed
    assert not (repo / "CLAUDE.md").exists()
    assert not (repo / "CODEX.md").exists()


def test_refresh_overwrites_edited_block(repo) -> None:
    apply_bundle(repo, _bundle(), source="test")
    agents_path = repo / "AGENTS.md"
    tampered = agents_path.read_text(encoding="utf-8").replace(
        "Worktree discipline etc.", "I DELETED THE RULES"
    )
    agents_path.write_text(tampered, encoding="utf-8")

    apply_bundle(repo, _bundle(), operation="refresh", source="test")
    restored = agents_path.read_text(encoding="utf-8")
    assert "Worktree discipline etc." in restored
    assert "I DELETED THE RULES" not in restored
