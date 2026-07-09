"""Coverage-heavy tests for doctor filesystem HCs: helpers, doc-drift, agents.

Hook + session HCs live in test_doctor_filesystem_full_hooks.py.
Repo file HCs live in test_doctor_filesystem_full_repo.py and
test_doctor_filesystem_full_repo2.py.
Template + schema + body HCs live in test_doctor_filesystem_full_template.py.

Schema scaffolding shared via _doctor_filesystem_full_test_helpers (private module).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_core.engines.doctor import (
    RecordCollector,
    _github_auth_configured,
    _resolve_main_root,
    _resolve_repo_root,
    hc_agent_consistency,
    hc_doc_drift,
    hc_doc_health,
    hc_prompt_command_consistency,
    hc_prompt_doctrine_consistency,
    hc_size_bloat,
)

from yoke_core.engines._doctor_filesystem_full_test_helpers import (
    _args,
    _cp,
    _make_conn,
    _run_hc,
)


class TestDoctorHelpers:
    def test_resolve_repo_root_returns_git_toplevel(self):
        with patch("yoke_core.engines.doctor_report._run", return_value=_cp(stdout="/repo\n")):
            assert _resolve_repo_root() == "/repo"

    def test_resolve_repo_root_returns_none_on_failure(self):
        with patch("yoke_core.engines.doctor_report._run", return_value=_cp(returncode=1)):
            assert _resolve_repo_root() is None

    def test_resolve_main_root_from_worktree_gitfile(self, tmp_path):
        main_root = tmp_path / "main"
        worktree_root = tmp_path / "wt"
        worktree_git = main_root / ".git" / "worktrees" / "YOK-1246"
        worktree_git.mkdir(parents=True)
        main_root.mkdir(exist_ok=True)
        worktree_root.mkdir()
        (worktree_root / ".git").write_text(f"gitdir: {worktree_git}\n")
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(worktree_root)):
            assert _resolve_main_root() == str(main_root)

    def test_resolve_main_root_falls_back_to_repo_root(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / ".git").mkdir()
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(repo_root)):
            assert _resolve_main_root() == str(repo_root)

    def test_github_auth_configured_returns_true_when_resolver_succeeds(self):
        """_github_auth_configured is True iff resolve_project_github_auth succeeds."""
        from yoke_core.domain.project_github_auth import (
            MissingCapability, ProjectGithubAuth,
        )
        auth = ProjectGithubAuth(
            project="yoke", repo="o/r", token="t", env={"GH_TOKEN": "t"},
        )
        with patch(
            "yoke_core.engines.doctor_hc_worktrees.resolve_project_github_auth",
            return_value=auth,
        ):
            assert _github_auth_configured() is True
        with patch(
            "yoke_core.engines.doctor_hc_worktrees.resolve_project_github_auth",
            side_effect=MissingCapability("yoke", "no capability"),
        ):
            assert _github_auth_configured() is False

    def test_canonical_resolver_injects_gh_token_env(self, tmp_path, monkeypatch):
        """Resolver returns a frozen auth bundle whose env carries
        ``GH_TOKEN`` for downstream ``subprocess.run`` calls."""
        from yoke_core.domain import projects as p
        from yoke_core.domain.project_github_auth import resolve_project_github_auth

        db = str(tmp_path / "doctor.db")
        p.cmd_init(db_path=db)
        from yoke_core.domain.db_helpers import connect
        from yoke_core.domain.project_seed_test_helpers import (
            seed_project_identities,
        )
        conn = connect(db)
        try:
            seed_project_identities(conn)
        finally:
            conn.close()
        p.cmd_capability_set_settings(
            "buzz", "github",
            '{"repo_owner":"example-org","repo_name":"buzz"}',
            base_settings_json=None, create=True, db_path=db,
        )
        p.cmd_capability_set_secret(
            "buzz", "github", "token", "ghs_secret",
            source="literal", db_path=db,
        )
        auth = resolve_project_github_auth("buzz", db_path=db)
        assert auth.env["GH_TOKEN"] == "ghs_secret"
        assert auth.repo == "example-org/buzz"

    def test_canonical_resolver_raises_missing_capability(self, tmp_path):
        """Missing capability raises a typed diagnostic so doctor HCs can
        translate to FAIL with a concrete repair command."""
        from yoke_core.domain import projects as p
        from yoke_core.domain.project_github_auth import (
            MissingCapability,
            resolve_project_github_auth,
        )

        db = str(tmp_path / "doctor.db")
        p.cmd_init(db_path=db)
        with pytest.raises(MissingCapability):
            resolve_project_github_auth("not-a-project", db_path=db)


class TestDocDrift:
    def test_warns_when_source_changes_without_doc_update(self, tmp_path):
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)), patch(
            "yoke_core.engines.doctor_report._run",
            return_value=_cp(
                stdout=(
                    "COMMIT abcdef123456\n"
                    ".agents/skills/yoke/scripts/example.sh\n\n"
                    "COMMIT deadbeef000000\n"
                    ".agents/skills/yoke/scripts/example.sh\n"
                    "runtime/docs/example.md\n"
                )
            ),
        ):
            rec = _run_hc(hc_doc_drift)
        assert rec.results[0].result == "WARN"
        assert "changed source without doc update" in rec.results[0].detail

    def test_passes_when_git_log_fails(self, tmp_path):
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)), patch(
            "yoke_core.engines.doctor_report._run", return_value=_cp(returncode=1)
        ):
            rec = _run_hc(hc_doc_drift)
        assert rec.results[0].result == "PASS"

    def test_passes_when_source_changes_include_doc_updates(self, tmp_path):
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)), patch(
            "yoke_core.engines.doctor_report._run",
            return_value=_cp(
                stdout=(
                    "COMMIT abcdef123456\n"
                    ".agents/skills/yoke/scripts/example.sh\n"
                    "runtime/docs/example.md\n"
                )
            ),
        ):
            rec = _run_hc(hc_doc_drift)
        assert rec.results[0].result == "PASS"


class TestAgentConsistency:
    def test_passes_without_repo_root(self):
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=None):
            rec = _run_hc(hc_agent_consistency)
        assert rec.results[0].result == "PASS"

    def test_passes_without_agents_dir(self, tmp_path):
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_agent_consistency)
        assert rec.results[0].result == "PASS"

    def test_fails_when_agent_references_missing_hook(self, tmp_path):
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "yoke-test.md").write_text(
            "---\ncommand: \".agents/hooks/missing.sh\"\n---\n"
        )
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_agent_consistency)
        assert rec.results[0].result == "FAIL"
        assert "does not exist" in rec.results[0].detail

    def test_passes_when_command_is_shell_literal_or_existing_file(self, tmp_path):
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        hook = tmp_path / ".agents" / "hooks" / "exists.sh"
        hook.parent.mkdir(parents=True)
        hook.write_text("#!/bin/sh\n")
        (agents_dir / "yoke-shell.md").write_text("---\ncommand: \"sh missing.sh\"\n---\n")
        (agents_dir / "yoke-hook.md").write_text(
            "---\ncommand: \".agents/hooks/exists.sh\"\n---\n"
        )
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_agent_consistency)
        assert rec.results[0].result == "PASS"

    def test_passes_when_command_is_single_quoted_shell_literal(self, tmp_path):
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "yoke-shell.md").write_text(
            "---\n"
            "command: 'echo ''BLOCKED: Tester cannot write files'' >&2 && exit 1'\n"
            "---\n"
        )
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_agent_consistency)
        assert rec.results[0].result == "PASS"

    def test_passes_when_command_is_python_module_with_env_prefix(self, tmp_path):
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        module = tmp_path / "runtime" / "api" / "domain" / "observe_pre.py"
        module.parent.mkdir(parents=True)
        module.write_text("def main():\n    return 0\n")
        (agents_dir / "yoke-python.md").write_text(
            "---\n"
            'command: "YOKE_DB=\\"${CLAUDE_PROJECT_DIR:-$PWD}/data/yoke.db\\" python3 -m yoke_core.domain.observe_pre"\n'
            "---\n"
        )
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_agent_consistency)
        assert rec.results[0].result == "PASS"
