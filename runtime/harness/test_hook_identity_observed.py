"""Client-observed version and machine facts on hook registration."""

from __future__ import annotations

from yoke_harness.hooks import identity_observed, identity_relay
from yoke_harness.session_relay_surface_probes import SurfaceProbeResult


def test_executor_version_answers_from_a_fresh_cached_observation(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "yoke_harness.session_relay_surface_probe_cache.cached_surface_versions",
        lambda **_kwargs: {"codex-desktop": "26.818.31338"},
    )
    monkeypatch.setattr(
        "yoke_harness.session_relay_surface_probe_cache.bounded_surface_probe",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("a fresh cached observation must answer directly")
        ),
    )

    assert identity_observed.client_executor_version("codex-desktop") == (
        "26.818.31338"
    )
    assert identity_observed.client_executor_version("") is None
    assert identity_observed.client_executor_version(None) is None


def test_executor_version_ignores_a_launcher_version_in_the_environment(
    monkeypatch,
) -> None:
    """A pooled harness process outlives the version that launched it."""
    monkeypatch.setenv("YOKE_EXECUTOR_VERSION", "2.1.245")
    monkeypatch.setenv("CLAUDE_CODE_VERSION", "2.1.245")
    monkeypatch.setattr(
        "yoke_harness.session_relay_surface_probe_cache.cached_surface_versions",
        lambda **_kwargs: {"claude-cli": "2.1.246"},
    )

    assert identity_observed.client_executor_version("claude-cli") == "2.1.246"


def test_executor_version_probes_and_caches_a_stale_cli_surface(
    monkeypatch,
) -> None:
    probed: list[str] = []

    def probe(surface: str, **_kwargs):
        probed.append(surface)
        return SurfaceProbeResult(
            surface, "exec", "ok", "0.150.0", 12, None, 1787780021.0
        )

    cached: list[tuple] = []
    monkeypatch.setattr(
        "yoke_harness.session_relay_surface_probe_cache.cached_surface_versions",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        "yoke_harness.session_relay_surface_probe_cache.bounded_surface_probe",
        probe,
    )
    monkeypatch.setattr(
        "yoke_harness.session_relay_surface_probe_cache.update_surface_probe_cache",
        lambda results, **kwargs: cached.append(tuple(results)),
    )

    assert identity_observed.client_executor_version("codex-cli") == "0.150.0"
    assert probed == ["codex-cli"]
    assert cached and cached[0][0].version == "0.150.0"


def test_executor_version_is_unknown_when_the_surface_cannot_be_observed(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "yoke_harness.session_relay_surface_probe_cache.cached_surface_versions",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        "yoke_harness.session_relay_surface_probe_cache.bounded_surface_probe",
        lambda surface, **_kwargs: SurfaceProbeResult(
            surface,
            "exec",
            "missing",
            None,
            3,
            "executable 'cursor-agent' was not found",
            1787780021.0,
        ),
    )

    assert identity_observed.client_executor_version("cursor-cli") is None


def test_machine_id_enrichment_is_best_effort(monkeypatch) -> None:
    monkeypatch.setattr(
        identity_observed,
        "ensure_machine_id",
        lambda: "machine-uuid",
    )
    assert identity_observed.client_machine_id() == "machine-uuid"

    def _unconfigured():
        raise RuntimeError("no machine config")

    monkeypatch.setattr(identity_observed, "ensure_machine_id", _unconfigured)
    assert identity_observed.client_machine_id() is None


def test_relay_identity_payload_includes_observed_fields(monkeypatch) -> None:
    monkeypatch.setattr(identity_relay, "client_entrypoint", lambda *_: "codex-cli")
    monkeypatch.setattr(identity_relay, "client_model", lambda *_: "gpt-test")
    monkeypatch.setattr(identity_relay, "client_lane", lambda *_: "primary")
    monkeypatch.setattr(identity_relay, "client_project_id", lambda *_: 7)
    monkeypatch.setattr(
        identity_relay,
        "client_executor_version",
        lambda *_args, **_kwargs: "0.148.0",
    )
    monkeypatch.setattr(
        identity_relay,
        "client_machine_id",
        lambda: "machine-uuid",
    )

    identity = identity_relay.relay_identity_payload(
        "SessionStart",
        {"session_id": "s-1"},
        "codex",
    )

    assert identity["executor_version"] == "0.148.0"
    assert identity["machine_id"] == "machine-uuid"
