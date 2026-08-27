"""One observed surface version serves heartbeat, launch, and registration.

The machine advertises a surface version, a launch quotes that advertisement,
and every session running on the machine registers one. When those answers come
from different sources they disagree, and no operator binding can satisfy both:
a version-gated route reads a build the machine does not run. These tests pin
the single observation every one of those readers answers from.
"""

from __future__ import annotations

import json
from pathlib import Path
import time

from yoke_core.hooks.registration_observed import enrich_local_observed_facts
from yoke_harness.hooks import identity_observed
from yoke_harness.session_relay_environment import native_session_environment
from yoke_harness.session_relay_inventory import collect_cached_inventory
from yoke_harness.session_relay_surface_probe_cache import (
    SURFACE_PROBE_CACHE_FILE_NAME,
    SURFACE_VERSION_MAX_AGE_SECONDS,
    observe_surface_version,
    observed_surface_version,
    refresh_surface_probe_cache,
    update_surface_probe_cache,
)
from yoke_harness.session_relay_surface_probes import SurfaceProbeResult
import yoke_harness.session_relay_inventory as inventory_module


INSTALLED_VERSION = "2.1.246"
SUPERSEDED_VERSION = "2.1.245"
SURFACE = "claude-cli"


def _installed_probe(surface: str) -> SurfaceProbeResult:
    """Stand in for running the surface's own executable with ``--version``."""
    return SurfaceProbeResult(
        surface, "exec", "ok", INSTALLED_VERSION, 55, None, time.time()
    )


def _cache_entry(state_dir: Path, surface: str = SURFACE) -> dict:
    """Read one surface's entry back off the shared probe cache."""
    document = json.loads(
        (state_dir / SURFACE_PROBE_CACHE_FILE_NAME).read_text(encoding="utf-8")
    )
    return document["surfaces"][surface]


def _machine_facts(monkeypatch) -> None:
    monkeypatch.setattr(
        inventory_module,
        "ensure_machine_id",
        lambda: "11111111-1111-4111-8111-111111111111",
    )
    monkeypatch.setattr(
        inventory_module.machine_config,
        "configured_projects",
        lambda **_kwargs: [],
    )
    monkeypatch.setattr(inventory_module, "local_handshake_version", lambda: "source")


def test_registration_records_the_version_the_probe_reports(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _machine_facts(monkeypatch)
    monkeypatch.setenv("YOKE_EXECUTOR_VERSION", SUPERSEDED_VERSION)
    probed = refresh_surface_probe_cache(
        SURFACE, state_dir=tmp_path, probe=_installed_probe
    )

    advertised = collect_cached_inventory(state_dir=tmp_path).surface_versions
    registered = observed_surface_version(SURFACE, state_dir=tmp_path)

    assert probed[0]["version"] == INSTALLED_VERSION
    assert advertised[SURFACE] == INSTALLED_VERSION
    assert registered == INSTALLED_VERSION


def test_registration_observes_a_surface_the_heartbeat_has_not_cached(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "yoke_harness.session_relay_surface_probe_cache.cached_surface_versions",
        lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        "yoke_harness.session_relay_surface_probe_cache.bounded_surface_probe",
        lambda surface, **_kwargs: _installed_probe(surface),
    )
    monkeypatch.setattr(
        "yoke_harness.session_relay_surface_probe_cache.update_surface_probe_cache",
        lambda *_args, **_kwargs: None,
    )

    assert observed_surface_version(SURFACE, state_dir=tmp_path) == INSTALLED_VERSION
    assert (
        identity_observed.client_executor_version("claude-code", "cli")
        == INSTALLED_VERSION
    )


def test_a_launch_mints_no_version_fact_for_the_child_to_inherit() -> None:
    """A launcher's belief must not outlive the process it described.

    A harness that serves a launch from a pre-warmed process pool hands the
    instruction to a process started long before, so any version stamped at
    launch describes a build that process may no longer be running.
    """
    environment = native_session_environment(
        executor="claude-code",
        provider="anthropic",
        environ={"PATH": "/opt/native/bin"},
    )

    assert not [name for name in environment if name.endswith("EXECUTOR_VERSION")]
    assert environment["YOKE_EXECUTOR"] == "claude-code"


def test_a_failed_probe_serves_the_last_version_the_surface_ever_reported(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """An unobservable surface is not a versionless one.

    An empty version meets no declared floor, so writing one turns a surface
    that briefly could not answer into one no version-gated route will ever
    accept. The last recorded version answers instead, marked as coming from
    the cache rather than from this reader's own observation.
    """
    aged = time.time() - (SURFACE_VERSION_MAX_AGE_SECONDS * 4)
    update_surface_probe_cache(
        (
            SurfaceProbeResult(
                SURFACE, "exec", "ok", INSTALLED_VERSION, 55, None, aged
            ),
        ),
        state_dir=tmp_path,
    )
    monkeypatch.setattr(
        "yoke_harness.session_relay_surface_probe_cache.bounded_surface_probe",
        lambda surface, **_kwargs: SurfaceProbeResult(
            surface, "exec", "timeout", None, 1000, "timed out after 1s", time.time()
        ),
    )

    observation = observe_surface_version(SURFACE, state_dir=tmp_path)

    assert observation.version == INSTALLED_VERSION
    assert observation.source == "cache_fallback"
    assert "timed out after 1s" in (observation.reason or "")

    recorded = _cache_entry(tmp_path)
    assert recorded["last_version_source"] == "cache_fallback"
    assert recorded["latest_verdict"] == "timeout"


def test_an_empty_observation_names_its_cause_on_the_shared_cache(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """A version nobody can explain is a version nobody can repair."""
    monkeypatch.setattr(
        "yoke_harness.session_relay_surface_probe_cache.cached_surface_versions",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("relay state dir is gone")),
    )

    observation = observe_surface_version("claude-vscode", state_dir=tmp_path)

    assert observation.version is None
    assert observation.source == "none"
    assert "relay state dir is gone" in (observation.reason or "")
    assert "unknown relay surface" in (observation.reason or "")

    recorded = _cache_entry(tmp_path, surface="claude-vscode")
    assert recorded["last_version_reason"] == observation.reason


def test_a_local_registration_composes_the_surface_before_observing_it(
    monkeypatch,
) -> None:
    """The local transport reads the same shared cache the relay path does.

    A machine with no https control plane registers through this path instead
    of the relayed one, so the family-relative entrypoint its harness reports
    has to reach the shared probe key here too.
    """
    monkeypatch.setattr(
        "yoke_harness.session_relay_surface_probe_cache.cached_surface_versions",
        lambda **_kwargs: {SURFACE: INSTALLED_VERSION},
    )

    observed, _machine = enrich_local_observed_facts(
        "", "already-known", "claude-code", executor_surface="cli"
    )

    assert observed == INSTALLED_VERSION
