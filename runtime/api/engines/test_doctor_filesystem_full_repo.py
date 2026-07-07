"""Doctor filesystem HC tests: repo file health checks (part A).

Continuation in test_doctor_filesystem_full_repo2.py.

Schema scaffolding shared via _doctor_filesystem_full_test_helpers (private module).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from yoke_core.engines.doctor import (
    RecordCollector,
    _resolve_repo_root,
    hc_arch_consistency,
    hc_browser_substrate,
    hc_claudemd_drift,
    hc_config_validation,
    hc_doc_health,
    hc_prompt_command_consistency,
    hc_prompt_doctrine_consistency,
    hc_size_bloat,
    hc_stray_project_files,
)

from yoke_core.engines._doctor_filesystem_full_test_helpers import (
    _args,
    _cp,
    _make_conn,
    _run_hc,
)


class TestRepoFileHealthChecksA:
    def test_claudemd_drift_warns_on_stale_guidance(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text(
            "Use sed/awk/grep for JSON.\nThere is no jq dependency.\n"
        )
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_claudemd_drift)
        assert rec.results[0].result == "WARN"
        assert "json-helper.sh" in rec.results[0].detail

    def test_claudemd_drift_passes_when_file_is_clean(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("Use json-helper.sh for JSON.\n")
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_claudemd_drift)
        assert rec.results[0].result == "PASS"

    def test_doc_health_fails_on_broken_link(self, tmp_path):
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(parents=True)
        (tmp_path / "README.md").write_text("# Yoke\n")
        (docs_dir / "guide.md").write_text("[missing](missing.md)\n")
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_doc_health)
        assert rec.results[0].result == "FAIL"
        assert "broken link" in rec.results[0].detail

    def test_doc_health_passes_with_existing_targets(self, tmp_path, capsys):
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir(parents=True)
        (tmp_path / "README.md").write_text("# Yoke\n")
        (docs_dir / "guide.md").write_text("[ok](target.md)\n")
        (docs_dir / "target.md").write_text("present\n")
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_doc_health)
        out = capsys.readouterr().out
        assert rec.results[0].result == "PASS"
        assert "running HC-doc-health check-readme" in out
        assert "running HC-doc-health scan-doc-links 0/2" in out

    def test_size_bloat_warns_on_large_db_and_git_dir(self, tmp_path):
        data_root = tmp_path / "data"
        data_root.mkdir()
        db_path = data_root / "yoke.db"
        with db_path.open("wb") as handle:
            handle.truncate(105 * 1024 * 1024)
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)), patch(
            "yoke_core.engines.doctor_report._run", return_value=_cp(stdout="600000\t.git\n")
        ):
            rec = _run_hc(hc_size_bloat)
        assert rec.results[0].result == "WARN"
        assert "yoke.db is" in rec.results[0].detail
        assert ".git directory is" in rec.results[0].detail

    def test_prompt_command_consistency_fails_on_stale_events_syntax(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("Use yoke-db.sh events --limit 5\n")
        rules_dir = tmp_path / ".claude" / "rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "session.md").write_text("clean\n")
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_prompt_command_consistency)
        assert rec.results[0].result == "FAIL"
        assert "events --limit" in rec.results[0].detail

    def test_prompt_command_consistency_passes_with_tail_syntax(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("Use yoke-db.sh events tail --limit 5\n")
        rules_dir = tmp_path / ".claude" / "rules"
        rules_dir.mkdir(parents=True)
        (rules_dir / "session.md").write_text("events tail --limit 10\n")
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_prompt_command_consistency)
        assert rec.results[0].result == "PASS"

    def test_prompt_doctrine_consistency_requires_philosophy_doc(self, tmp_path):
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_prompt_doctrine_consistency)
        assert rec.results[0].result == "FAIL"

    def test_prompt_doctrine_consistency_passes_when_doc_exists(self, tmp_path):
        doc = tmp_path / "docs" / "prompt-philosophy.md"
        doc.parent.mkdir(parents=True)
        doc.write_text("philosophy\n")
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_prompt_doctrine_consistency)
        assert rec.results[0].result == "PASS"

    def test_stray_project_files_fail_when_root_level_dirs_exist(self, tmp_path):
        (tmp_path / "deployments").mkdir(parents=True)
        (tmp_path / "workflows").mkdir()
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_stray_project_files)
        assert rec.results[0].result == "FAIL"
        assert "managed project repo or scratch/deploy-run output" in rec.results[0].detail

    def test_stray_project_files_pass_without_repo_root(self):
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=None):
            rec = _run_hc(hc_stray_project_files)
        assert rec.results[0].result == "PASS"
