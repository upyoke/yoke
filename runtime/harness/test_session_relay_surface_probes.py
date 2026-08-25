"""Relay surface probes retain bounded evidence without delaying registration."""

from __future__ import annotations

from pathlib import Path
import subprocess
from threading import Event
from types import SimpleNamespace

from yoke_harness import session_relay
from yoke_harness import session_relay_surface_probe_cache as probe_cache
from yoke_harness import session_relay_surface_probes as probes
from yoke_harness.session_relay_inventory import RelayInventory


def _result(
    *,
    verdict: str,
    observed_at: float,
    version: str | None = None,
    error: str | None = None,
) -> probes.SurfaceProbeResult:
    return probes.SurfaceProbeResult(
        surface="claude-cli",
        source="exec",
        verdict=verdict,
        version=version,
        duration_ms=25,
        error=error,
        observed_at=observed_at,
    )


def test_cli_probe_uses_generous_timeout_and_reports_timeout(monkeypatch) -> None:
    seen: dict[str, float] = {}
    monkeypatch.setattr(probes, "resolve_native_cli", lambda _name: "/bin/claude")

    def timeout_runner(*_args, **kwargs):
        seen["timeout"] = kwargs["timeout"]
        raise subprocess.TimeoutExpired("claude", kwargs["timeout"])

    result = probes.probe_cli_surface(
        "claude-cli",
        ("claude", "--version"),
        runner=timeout_runner,
    )

    assert probes.SURFACE_PROBE_TIMEOUT_SECONDS >= 30
    assert seen["timeout"] == probes.SURFACE_PROBE_TIMEOUT_SECONDS
    assert result.verdict == "timeout"
    assert result.version is None
    assert "timed out" in str(result.error)


def test_failed_probe_advertises_bounded_last_known_good_as_stale(
    tmp_path: Path,
) -> None:
    probe_cache.update_surface_probe_cache(
        [_result(verdict="ok", version="2.1.241", observed_at=100)],
        state_dir=tmp_path,
    )

    diagnostics = probe_cache.refresh_surface_probe_cache(
        "claude-cli",
        state_dir=tmp_path,
        probe=lambda _surface: _result(
            verdict="timeout",
            error="timed out after 30s",
            observed_at=120,
        ),
        now=120,
    )

    assert probe_cache.cached_surface_versions(state_dir=tmp_path, now=120) == {
        "claude-cli": "2.1.241"
    }
    assert diagnostics[0]["advertised_version"] == "2.1.241"
    assert diagnostics[0]["cache_state"] == "stale"
    assert diagnostics[0]["stale"] is True
    assert diagnostics[0]["error"] == "timed out after 30s"


def test_last_known_good_expires_at_the_bounded_age(tmp_path: Path) -> None:
    probe_cache.update_surface_probe_cache(
        [_result(verdict="ok", version="2.1.241", observed_at=100)],
        state_dir=tmp_path,
    )

    expired_at = 100 + probe_cache.SURFACE_VERSION_MAX_AGE_SECONDS + 1
    assert probe_cache.cached_surface_versions(state_dir=tmp_path, now=expired_at) == {}


def test_one_unexpected_probe_failure_does_not_discard_other_results() -> None:
    def probe(surface: str) -> probes.SurfaceProbeResult:
        if surface == "claude-cli":
            raise RuntimeError("probe crashed")
        return probes.SurfaceProbeResult(
            surface=surface,
            source="exec",
            verdict="ok",
            version="1.2.3",
            duration_ms=1,
            error=None,
            observed_at=100,
        )

    failed, healthy = probes.probe_surfaces(
        ("claude-cli", "codex-cli"),
        probe=probe,
    )

    assert failed.verdict == "error"
    assert failed.error == "RuntimeError: probe crashed"
    assert healthy.verdict == "ok"
    assert healthy.version == "1.2.3"


def test_relay_registration_runs_while_probe_refresh_is_in_flight(
    tmp_path: Path,
) -> None:
    refresh_started = Event()
    registration_started = Event()

    def refresh() -> None:
        refresh_started.set()
        assert registration_started.wait(1)

    def dispatch(**_kwargs):
        assert refresh_started.wait(1)
        registration_started.set()
        return SimpleNamespace(
            success=True,
            result={"state": "active", "next_poll_seconds": 60, "jobs": []},
        )

    inventory = RelayInventory(
        relay_id="machine:machine-1",
        machine_id="machine-1",
        hostname="relay-host",
        relay_version="source",
        project_ids=(1,),
        surface_versions={"claude-cli": "2.1.241"},
    )

    outcome = session_relay.serve_once(
        state_dir=tmp_path,
        inventory_provider=lambda: inventory,
        inventory_refresher=refresh,
        dispatcher=dispatch,
    )

    assert outcome.state == "active"
    assert refresh_started.is_set()
    assert registration_started.is_set()
