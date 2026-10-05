"""Doctor help probes retain every entry and share the parent deadline."""

import json
from contextlib import contextmanager
from types import SimpleNamespace

from yoke_contracts import doctor_budget
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


def test_help_probes_cover_both_rosters_and_keep_failure_order(monkeypatch, tmp_path):
    from yoke_project_checks import check_cli_help_handler as help_check
    from yoke_core.api import service_client
    from yoke_core.cli import db_router_dispatch

    monkeypatch.setattr(help_check, "_resolve_repo_root", lambda: str(tmp_path))
    monkeypatch.setattr(service_client, "COMMANDS", {"second": None, "first": None})
    monkeypatch.setattr(db_router_dispatch, "_DOMAIN_PY_MODULES", {"domain": None})

    @contextmanager
    def scratch(**kwargs):
        yield tmp_path

    monkeypatch.setattr(help_check, "scratch_subdir", scratch)
    observed = []

    def run(argv, **kwargs):
        observed.append((argv[2], argv[3], kwargs["timeout"]))
        return SimpleNamespace(returncode=1, stderr=b"bad help")

    monkeypatch.setattr(help_check.subprocess, "run", run)
    rec = RecordCollector()
    with doctor_budget.check_budget():
        help_check.hc_cli_help_handler_present(None, DoctorArgs(), rec)
    assert sorted(token for _, token, _ in observed) == ["domain", "first", "second"]
    assert all(0 < timeout <= 30 for _, _, timeout in observed)
    assert rec.results[0].result == "FAIL"
    assert rec.results[0].detail.splitlines() == [
        "service_client first: rc=1 stderr='bad help'",
        "service_client second: rc=1 stderr='bad help'",
        "db_router domain: rc=1 stderr='bad help'",
    ]


def test_isolated_atlas_help_preserves_complete_payload_and_budget(monkeypatch):
    import subprocess
    from yoke_core.engines.doctor_cli_help_capture import collect_help_pages_isolated

    roster = {
        "count": 2,
        "rows": [{"cli_tokens": ["first"]}, {"cli_tokens": ["second"]}],
    }
    expected = {
        "per_subcommand": {"first": {"exit_code": 0}, "second": {"exit_code": 2}}
    }
    observed = []

    def run(argv, **kwargs):
        observed.append(kwargs)
        assert json.loads(kwargs["input"]) == roster
        return SimpleNamespace(returncode=0, stdout=json.dumps(expected))

    monkeypatch.setattr(subprocess, "run", run)
    with doctor_budget.check_budget():
        assert collect_help_pages_isolated(roster) == expected
    assert 0 < observed[0]["timeout"] <= doctor_budget.CHECK_BUDGET_S


def test_atlas_child_timeout_discards_partial_doctor_verdicts(monkeypatch):
    import subprocess
    from yoke_core.engines.doctor_cli_help_capture import collect_help_pages_isolated
    from yoke_core.engines.doctor_check_execution import execute_check_isolated
    from yoke_core.engines.doctor_registry_types import HealthCheck

    def timed_out(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", timed_out)

    def check(conn, args, rec):
        rec.record("HC-partial", "Partial", "PASS", "")
        collect_help_pages_isolated({"count": 0, "rows": []})

    rec = RecordCollector()
    execute_check_isolated(
        object(), DoctorArgs(), rec, HealthCheck("atlas", "Atlas", check)
    )
    assert [row.check_id for row in rec.results] == ["HC-check-incomplete"]
