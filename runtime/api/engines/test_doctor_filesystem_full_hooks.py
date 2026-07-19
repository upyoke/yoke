"""Doctor filesystem HC tests: hook executability + stale-session HCs.

Helpers/doc-drift/agent HCs live in test_doctor_filesystem_full.py.
Repo file HCs live in test_doctor_filesystem_full_repo.py and
test_doctor_filesystem_full_repo2.py.
Schema + body HCs live in test_doctor_filesystem_full_schema_config.py.

Schema scaffolding shared via _doctor_filesystem_full_test_helpers (private module).
"""

from __future__ import annotations

import os

from unittest.mock import patch

from yoke_core.engines.doctor import (
    hc_hook_executability,
    hc_self_test,
    hc_stale_session_reclaimer_alive,
    hc_stale_sessions,
)

from yoke_core.engines._doctor_filesystem_full_test_helpers import (
    _cp,
    _make_conn,
    _run_hc,
)


class TestHookExecutability:
    def test_passes_without_repo_root(self):
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=None):
            rec = _run_hc(hc_hook_executability)
        assert rec.results[0].result == "PASS"

    def test_passes_without_agents_dir(self, tmp_path):
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_hook_executability)
        assert rec.results[0].result == "PASS"

    def test_fails_when_hook_exists_but_is_not_executable(self, tmp_path):
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        hook = tmp_path / ".agents" / "hooks" / "exists.sh"
        hook.parent.mkdir(parents=True)
        hook.write_text("#!/bin/sh\n")
        hook.chmod(0o644)
        (agents_dir / "yoke-hook.md").write_text(
            "---\ncommand: \".agents/hooks/exists.sh\"\n---\n"
        )
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_hook_executability)
        assert rec.results[0].result == "FAIL"
        assert "not executable" in rec.results[0].detail

    def test_passes_when_hook_is_executable(self, tmp_path):
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        hook = tmp_path / ".agents" / "hooks" / "exists.sh"
        hook.parent.mkdir(parents=True)
        hook.write_text("#!/bin/sh\n")
        hook.chmod(0o755)
        (agents_dir / "yoke-hook.md").write_text(
            "---\ncommand: \".agents/hooks/exists.sh\"\n---\n"
        )
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_hook_executability)
        assert rec.results[0].result == "PASS"

    def test_ignores_shell_literal_commands(self, tmp_path):
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "yoke-hook.md").write_text("---\ncommand: \"bash missing.sh\"\n---\n")
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_hook_executability)
        assert rec.results[0].result == "PASS"

    def test_ignores_python_module_commands(self, tmp_path):
        agents_dir = tmp_path / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "yoke-hook.md").write_text(
            "---\ncommand: \"python3 -m yoke_core.domain.observe_pre\"\n---\n"
        )
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_hook_executability)
        assert rec.results[0].result == "PASS"


class TestSelfTest:
    def test_warns_without_repo_root(self):
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=None):
            rec = _run_hc(hc_self_test)
        assert rec.results[0].result == "WARN"

    def test_warns_when_entrypoint_missing(self, tmp_path):
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_self_test)
        assert rec.results[0].result == "WARN"

    def test_fails_when_check_prerequisites_fails(self, tmp_path):
        script = tmp_path / "runtime" / "api" / "domain" / "check_prerequisites.py"
        script.parent.mkdir(parents=True)
        script.write_text("def main():\n    return 0\n")
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)), patch(
            "yoke_core.engines.doctor_report._run",
            return_value=_cp(returncode=1, stdout="oops", stderr="bad"),
        ):
            rec = _run_hc(hc_self_test)
        assert rec.results[0].result == "FAIL"
        assert "reported failures" in rec.results[0].detail

    def test_passes_when_check_prerequisites_succeeds(self, tmp_path):
        script = tmp_path / "runtime" / "api" / "domain" / "check_prerequisites.py"
        script.parent.mkdir(parents=True)
        script.write_text("def main():\n    return 0\n")
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)), patch(
            "yoke_core.engines.doctor_report._run", return_value=_cp(returncode=0)
        ):
            rec = _run_hc(hc_self_test)
        assert rec.results[0].result == "PASS"


class TestStaleSessions:
    def test_passes_without_repo_root(self):
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=None):
            rec = _run_hc(hc_stale_sessions)
        assert rec.results[0].result == "PASS"

    def test_passes_when_registry_disabled(self, tmp_path):
        data_root = tmp_path / "data"
        data_root.mkdir()
        (data_root / "config").write_text("session_registry_enabled=false\n")
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_stale_sessions)
        assert rec.results[0].result == "PASS"

    def test_passes_when_registry_enabled_but_no_sessions_dir(self, tmp_path):
        data_root = tmp_path / "data"
        data_root.mkdir()
        (data_root / "config").write_text("session_registry_enabled=true\n")
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)):
            rec = _run_hc(hc_stale_sessions)
        assert rec.results[0].result == "PASS"

    def test_warns_on_old_session_files(self, tmp_path):
        data_root = tmp_path / "data"
        sessions_dir = data_root / "sessions"
        sessions_dir.mkdir(parents=True)
        (data_root / "config").write_text("session_registry_enabled=true\n")
        stale = sessions_dir / "old.session"
        stale.write_text("session")
        old_epoch = 1_700_000_000
        os.utime(stale, (old_epoch, old_epoch))
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)), patch(
            "yoke_core.engines.doctor_report.time.time", return_value=old_epoch + 20_000
        ):
            rec = _run_hc(hc_stale_sessions)
        assert rec.results[0].result == "WARN"
        assert "stale" in rec.results[0].detail

    def test_passes_on_fresh_session_files(self, tmp_path):
        data_root = tmp_path / "data"
        sessions_dir = data_root / "sessions"
        sessions_dir.mkdir(parents=True)
        (data_root / "config").write_text("session_registry_enabled=true\n")
        fresh = sessions_dir / "new.session"
        fresh.write_text("session")
        fresh_epoch = 1_700_020_000
        os.utime(fresh, (fresh_epoch, fresh_epoch))
        with patch("yoke_core.engines.doctor_report._resolve_repo_root", return_value=str(tmp_path)), patch(
            "yoke_core.engines.doctor_report.time.time", return_value=fresh_epoch + 60
        ):
            rec = _run_hc(hc_stale_sessions)
        assert rec.results[0].result == "PASS"


class TestStaleSessionReclaimerAlive:
    def test_passes_without_events_table(self):
        rec = _run_hc(hc_stale_session_reclaimer_alive)
        assert rec.results[0].result == "PASS"

    def test_warns_when_no_sweep_event_exists(self):
        conn = _make_conn()
        conn.execute(
            """
            CREATE TABLE events (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                event_name TEXT,
                created_at TEXT
            )
            """
        )
        rec = _run_hc(hc_stale_session_reclaimer_alive, conn=conn)
        assert rec.results[0].result == "WARN"
        assert "HarnessSessionStaleSweepCompleted" in rec.results[0].detail

    def test_passes_with_recent_sweep_event(self):
        conn = _make_conn()
        conn.execute(
            """
            CREATE TABLE events (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                event_name TEXT,
                created_at TEXT
            )
            """
        )
        from datetime import datetime as _dt, timedelta as _td, timezone as _tz
        thirty_min_ago = (_dt.now(_tz.utc) - _td(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            "INSERT INTO events (event_name, created_at) VALUES (%s, %s)",
            ("HarnessSessionStaleSweepCompleted", thirty_min_ago),
        )
        rec = _run_hc(hc_stale_session_reclaimer_alive, conn=conn)
        assert rec.results[0].result == "PASS"
        assert "Last sweep" in rec.results[0].detail
