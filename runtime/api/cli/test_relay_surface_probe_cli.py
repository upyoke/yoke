"""Machine-local relay probe diagnostics expose every surface verdict."""

from __future__ import annotations

import json

from yoke_cli.commands import registry_session_control
from yoke_cli.commands.adapters import session_control_relay as relay
from yoke_harness import session_relay_surface_probe_cache as probe_cache


def _probe(
    surface: str,
    *,
    verdict: str,
    version: str | None,
    advertised: str | None,
    error: str | None,
) -> dict[str, object]:
    return {
        "surface": surface,
        "source": "exec",
        "verdict": verdict,
        "version": version,
        "duration_ms": 41,
        "error": error,
        "observed_at": 1.0,
        "advertised_version": advertised,
        "cache_state": "stale" if verdict != "ok" and advertised else "fresh",
        "stale": verdict != "ok" and advertised is not None,
        "stale_age_seconds": 30 if advertised else None,
    }


def test_probe_surface_json_names_live_failure_and_stale_fallback(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        probe_cache,
        "refresh_surface_probe_cache",
        lambda surface=None: (
            _probe(
                surface or "claude-cli",
                verdict="timeout",
                version=None,
                advertised="2.1.241",
                error="timed out after 30s",
            ),
        ),
    )

    assert relay.relay_probe_surface(["--surface", "claude-cli", "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["probes"][0] == {
        **_probe(
            "claude-cli",
            verdict="timeout",
            version=None,
            advertised="2.1.241",
            error="timed out after 30s",
        )
    }


def test_probe_surface_human_output_has_per_surface_diagnostics(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(
        probe_cache,
        "refresh_surface_probe_cache",
        lambda _surface=None: (
            _probe(
                "cursor-cli",
                verdict="ok",
                version="2026.08.25",
                advertised="2026.08.25",
                error=None,
            ),
        ),
    )

    assert relay.relay_probe_surface([]) == 0
    rendered = capsys.readouterr().out
    assert rendered.splitlines()[0] == "RELAY SURFACE PROBES"
    assert "SURFACE" in rendered and "VERDICT" in rendered
    assert "DURATION (MS)" in rendered and "ERROR" in rendered
    assert "cursor-cli" in rendered and "2026.08.25" in rendered


def test_probe_surface_is_registered_as_machine_local_tool() -> None:
    route = registry_session_control.SESSION_CONTROL_TOOL_SHAPED_SUBCOMMANDS[
        ("relay", "probe-surface")
    ]

    assert route is relay.relay_probe_surface
    assert (
        registry_session_control.SESSION_CONTROL_TOOL_SHAPED_USAGE[
            "yoke relay probe-surface"
        ]
        == relay.RELAY_PROBE_SURFACE_USAGE
    )
