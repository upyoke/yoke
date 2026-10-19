"""Atlas help capture keeps its complete payload and shares the doctor deadline."""

import json
from types import SimpleNamespace

from yoke_contracts import doctor_budget
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


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
