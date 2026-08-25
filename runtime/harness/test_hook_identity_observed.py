"""Client-observed version and machine facts on hook registration."""

from __future__ import annotations

from yoke_harness.hooks import identity_observed, identity_relay


def test_executor_version_uses_explicit_then_family_specific_environment(
    monkeypatch,
) -> None:
    assert (
        identity_observed.client_executor_version(
            "codex",
            environ={"CODEX_VERSION": "0.148.0"},
        )
        == "0.148.0"
    )
    assert (
        identity_observed.client_executor_version(
            "codex-cli",
            environ={
                "YOKE_EXECUTOR_VERSION": "pinned",
                "CODEX_VERSION": "ignored",
            },
        )
        == "pinned"
    )
    assert (
        identity_observed.client_executor_version(
            "cursor",
            environ={},
        )
        is None
    )
    monkeypatch.setattr(
        "yoke_harness.session_relay_surface_probe_cache.cached_surface_versions",
        lambda: {"codex-desktop": "26.818.31338"},
    )
    monkeypatch.setattr(
        "yoke_harness.session_relay_surface_probe_cache.refresh_surface_probe_cache",
        lambda _surface, **_kwargs: (_ for _ in ()).throw(
            AssertionError("cache must win")
        ),
    )
    assert (
        identity_observed.client_executor_version(
            "codex",
            executor_surface="codex-desktop",
            environ={},
        )
        == "26.818.31338"
    )


def test_executor_version_probes_and_caches_a_resolved_cli_surface(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "yoke_harness.session_relay_surface_probe_cache.cached_surface_versions",
        lambda: {},
    )
    observed: list[str] = []

    def refresh(surface: str, **kwargs):
        observed.append(surface)
        assert callable(kwargs["probe"])
        return ({"advertised_version": "0.150.0"},)

    monkeypatch.setattr(
        "yoke_harness.session_relay_surface_probe_cache.refresh_surface_probe_cache",
        refresh,
    )

    assert (
        identity_observed.client_executor_version(
            "codex",
            executor_surface="codex-cli",
            environ={},
        )
        == "0.150.0"
    )
    assert observed == ["codex-cli"]


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
