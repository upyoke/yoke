"""Plan-limit diagnosis precedes cached-window carry-forward on every surface."""

import logging

import pytest

from yoke_contracts.harness_cli_manifest import HARNESS_CLI_MANIFESTS
from yoke_contracts.session_control.plan_limits import unknown_reading
from yoke_harness import session_relay_plan_limits as limits
from yoke_harness.session_relay_failure_log import FailureReporter

NOW = "2026-10-29T20:35:00.000000Z"


@pytest.mark.parametrize("manifest", HARNESS_CLI_MANIFESTS)
@pytest.mark.parametrize("reason", ["credential_expired", "http_429", "usage_unreadable"])
def test_failed_polls_log_reason_once_then_recover(monkeypatch, caplog, manifest, reason):
    reporter = FailureReporter(clock=lambda: 0)
    monkeypatch.setattr(limits, "_failures", reporter)
    failed = unknown_reading(manifest.surface_id, reason, observed_at=NOW)
    recovered = {"windows": [{"status": "ok", "remaining_percent": 50}]}
    readings = iter([failed, failed, recovered, recovered, failed])
    monkeypatch.setitem(limits._PROBES, manifest.quota_source,
                        lambda **kwargs: next(readings))
    with caplog.at_level(logging.ERROR):
        assert limits._probe_one(manifest.surface_id, NOW) == failed
        assert limits._probe_one(manifest.surface_id, NOW) == failed
    assert len(caplog.records) == 1
    assert reason in caplog.text
    assert f"{manifest.surface_id} plan-limit probe failed" in caplog.text
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert limits._probe_one(manifest.surface_id, NOW) == recovered
        assert limits._probe_one(manifest.surface_id, NOW) == recovered
    assert len(caplog.records) == 1
    assert "recovered" in caplog.text
    assert "consecutive_failures=2" in caplog.text
    caplog.clear()
    limits._probe_one(manifest.surface_id, NOW)
    assert len(caplog.records) == 1
    assert reason in caplog.text


def test_raised_probe_uses_same_failure_and_recovery_path(monkeypatch, caplog):
    reporter = FailureReporter(clock=lambda: 0)
    monkeypatch.setattr(limits, "_failures", reporter)

    def broken(**kwargs):
        raise RuntimeError("vendor client failed")

    monkeypatch.setitem(limits._PROBES, "anthropic_oauth_usage", broken)
    for _ in range(2):
        reading = limits._probe_one("claude-cli", NOW)
        assert reading["windows"][0]["reason"] == "probe_raised_RuntimeError"
    assert len(caplog.records) == 1
    assert "probe_raised_RuntimeError" in caplog.text
