"""The relay remembers success and backs off failed setup attempts."""

from types import SimpleNamespace

from yoke_harness import session_relay_harness_reconcile as relay
from yoke_harness.harness_setup_reconcile import HarnessSetupResult, HarnessSetupRow


def test_change_only_and_failure_retry_backoff(monkeypatch, tmp_path):
    harnesses = [SimpleNamespace(harness_id="codex")]
    monkeypatch.setattr(relay, "installed_machine_hooks", lambda: harnesses)
    calls = []
    failure = HarnessSetupResult(
        (
            HarnessSetupRow(
                "config", "codex", "posture", "refused", "bad config", "repair config"
            ),
        )
    )
    results = [
        HarnessSetupResult(()),
        failure,
        HarnessSetupResult(()),
        HarnessSetupResult(()),
    ]

    def run():
        calls.append(True)
        return results.pop(0)

    monkeypatch.setattr(relay, "reconcile_harness_setup", run)
    path = tmp_path / "state.json"
    assert relay.reconcile_on_change(path=path, now=10)["fingerprint"] == ["codex"]
    saved = path.read_bytes()
    relay.reconcile_on_change(path=path, now=20)
    assert len(calls) == 1 and path.read_bytes() == saved
    harnesses.append(SimpleNamespace(harness_id="cursor"))
    state = relay.reconcile_on_change(path=path, now=30)
    assert state["fingerprint"] == ["codex"]
    assert state["failure"]["rows"][0]["recovery"] == "repair config"
    relay.reconcile_on_change(path=path, now=929)
    assert len(calls) == 2
    assert relay.reconcile_on_change(path=path, now=930)["failure"] is None
    harnesses.append(SimpleNamespace(harness_id="claude-code"))
    relay.reconcile_on_change(path=path, now=931)
    assert len(calls) == 4


def test_new_fingerprint_retries_failed_attempt_immediately(monkeypatch, tmp_path):
    monkeypatch.setattr(relay, "installed_machine_hooks", lambda: [])
    calls = []

    def fail():
        calls.append(True)
        raise OSError("denied")

    monkeypatch.setattr(relay, "reconcile_harness_setup", fail)
    path = tmp_path / "state.json"
    relay.reconcile_on_change(path=path, now=1)
    relay.reconcile_on_change(path=path, now=2)
    assert len(calls) == 1
    monkeypatch.setattr(
        relay, "installed_machine_hooks", lambda: [SimpleNamespace(harness_id="codex")]
    )
    state = relay.reconcile_on_change(path=path, now=3)
    assert len(calls) == 2
    assert "denied" in state["failure"]["reason"]


def test_inventory_callback_runs_setup_even_when_probe_fails(monkeypatch):
    import pytest

    called = []

    def fail():
        raise RuntimeError("probe unavailable")

    monkeypatch.setattr(relay, "refresh_surface_probe_cache", fail)
    monkeypatch.setattr(relay, "reconcile_on_change", lambda: called.append(True))
    with pytest.raises(RuntimeError, match="probe unavailable"):
        relay.refresh_harness_inventory()
    assert called == [True]
