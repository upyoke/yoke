"""Tests for the harness/session + substrate-parity health checks.

The engine bundle module exposes ``HARNESS_HEALTH_CHECKS`` as a constant. The
harness checks that only make sense against this repo's own hook wiring,
rendered adapters, and packaged bundles are registered as project checks
instead, discovered from ``.yoke/doctor/``.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.engines.doctor_project_checks import discover_project_checks
from yoke_core.engines.doctor_registry_harness import HARNESS_HEALTH_CHECKS
from yoke_core.engines.doctor_registry_types import HealthCheck


REPO_ROOT = Path(__file__).resolve().parents[3]

# Session/harness substrate checks the engine registers for every project.
_ENGINE_SESSION_SLUGS = (
    "stale-sessions",
    "stale-session-reclaimer-alive",
    "stale-reclaim-collision",
    "session-actor-binding",
    "local-operating-actor-authority",
    "session-cwd-binding",
    "session-pre-implementing-activity",
    "session-lane-mismatch",
)
_ENGINE_CONFIG_SLUGS = (
    "launcher-authority",
    "machine-registry",
    "session-relay",
    "session-relay-orphans",
    "harness-unattended-posture",
    "project-hook-config-validity",
    "pack-prerequisites",
)

# Session/harness substrate checks that read this repo's own hook wiring and
# machine browser runtime, so this project keeps them in ``.yoke/doctor/``.
_PROJECT_SESSION_SLUGS = (
    "session-startup-hook",
    "browser-substrate",
)

# Harness substrate parity / packaging drift checks — every renderer or
# snapshot output that must match its source. All of them compare this repo's
# rendered adapters and packaged bundles against their sources, so all of them
# are project checks rather than engine ones.
_SUBSTRATE_PARITY_SLUGS = (
    "harness-substrate-drift",
    "codex-hook-matchers",
    "codex-hook-floor",
    "codex-hook-doc-drift",
    "apply-patch-deny-smoke",
    "apply-patch-observe-smoke",
    "codex-agent-adapter-drift",
    "codex-subagent-surface-truth",
    "path-claim-bash-guard",
    "install-bundle-drift",
)

# Ledger-audit checks (cross-session mutation evidence). The claim-boundary
# audit reads control-plane rows every project has; the other two audit this
# repo's own emitter and executor vocabulary.
_ENGINE_LEDGER_AUDIT_SLUGS = ("claim-boundary-audit",)
_PROJECT_LEDGER_AUDIT_SLUGS = (
    "event-outcome-enum-coverage",
    "executor-canonicalization",
)

# Reflection-capture audit checks. The two event-count audits read rows any
# project's control plane has; the coverage check compares this repo's own
# rendered hook chains against the captures they produced.
_ENGINE_REFLECTION_SLUGS = (
    "reflection-capture-unhandled",
    "reflection-capture-persist-failed",
)
_PROJECT_REFLECTION_SLUGS = ("reflection-capture-hook-coverage",)


def _project_checks():
    """Every check this repo declares in ``.yoke/doctor/``."""
    discovery = discover_project_checks(REPO_ROOT)
    assert not discovery.failures, (
        "project check modules failed to import: "
        f"{[(f.path.name, f.error) for f in discovery.failures]}"
    )
    return discovery.checks


def test_bundle_contains_session_cwd_binding():
    slugs = [hc.slug for hc in HARNESS_HEALTH_CHECKS]
    assert "session-cwd-binding" in slugs


def test_bundle_entries_are_health_checks():
    for hc in HARNESS_HEALTH_CHECKS:
        assert isinstance(hc, HealthCheck)
        assert hc.slug
        assert hc.name
        assert callable(hc.fn)


def test_bundle_slugs_are_unique():
    slugs = [hc.slug for hc in HARNESS_HEALTH_CHECKS]
    assert len(set(slugs)) == len(slugs)


def test_bundle_holds_session_then_audit_checks_in_order():
    """Session checks precede the ledger audit, then the reflection audits."""
    slugs = [hc.slug for hc in HARNESS_HEALTH_CHECKS]
    assert slugs == (
        list(_ENGINE_SESSION_SLUGS)
        + list(_ENGINE_CONFIG_SLUGS)
        + list(_ENGINE_LEDGER_AUDIT_SLUGS)
        + list(_ENGINE_REFLECTION_SLUGS)
    )


def test_self_scoped_harness_slugs_registered_as_project_checks():
    """Harness checks scoped to this repo are project checks, not engine ones."""
    slugs = [hc.slug for hc in _project_checks()]
    engine_slugs = {hc.slug for hc in HARNESS_HEALTH_CHECKS}
    self_scoped = (
        _PROJECT_SESSION_SLUGS + _PROJECT_LEDGER_AUDIT_SLUGS + _PROJECT_REFLECTION_SLUGS
    )
    for slug in self_scoped:
        assert slugs.count(slug) == 1, (
            f"slug {slug!r} appears {slugs.count(slug)} times in the checks "
            f"discovered under {REPO_ROOT}"
        )
        assert slug not in engine_slugs


def test_each_substrate_parity_slug_registered_exactly_once():
    """Every substrate-parity / packaging-drift slug appears exactly once."""
    slugs = [hc.slug for hc in _project_checks()]
    for slug in _SUBSTRATE_PARITY_SLUGS:
        assert slugs.count(slug) == 1, (
            f"slug {slug!r} appears {slugs.count(slug)} times in the checks "
            f"discovered under {REPO_ROOT}"
        )


def test_substrate_parity_checks_use_canonical_dataclass_and_are_not_github_dependent():
    """The substrate parity checks are local-only (no github_dependent)."""
    by_slug = {hc.slug: hc for hc in _project_checks()}
    for slug in _SUBSTRATE_PARITY_SLUGS:
        hc = by_slug[slug]
        assert isinstance(hc, HealthCheck)
        assert callable(hc.fn)
        assert hc.github_dependent is False


def test_session_cwd_binding_id_unique_in_full_registry():
    """HC-session-cwd-binding does not collide with any other HC."""
    from yoke_core.engines.doctor_registry import HEALTH_CHECKS

    matches = [hc for hc in HEALTH_CHECKS if hc.slug == "session-cwd-binding"]
    assert len(matches) == 1


def test_full_registry_slugs_remain_unique():
    from yoke_core.engines.doctor_registry import HEALTH_CHECKS

    slugs = [hc.slug for hc in HEALTH_CHECKS]
    assert len(set(slugs)) == len(slugs), (
        f"duplicate slugs in HEALTH_CHECKS: {[s for s in slugs if slugs.count(s) > 1]}"
    )


def test_bundle_spliced_into_full_registry():
    from yoke_core.engines.doctor_registry import HEALTH_CHECKS

    full_slugs = [hc.slug for hc in HEALTH_CHECKS]
    for hc in HARNESS_HEALTH_CHECKS:
        assert hc.slug in full_slugs


def test_bundle_appends_after_existing_checks():
    """The bundle must be at the tail of the full registry (preserving order)."""
    from yoke_core.engines.doctor_registry import HEALTH_CHECKS

    slugs = [hc.slug for hc in HEALTH_CHECKS]
    bundle_slugs = [hc.slug for hc in HARNESS_HEALTH_CHECKS]
    last_n = slugs[-len(bundle_slugs) :]
    assert last_n == bundle_slugs


def test_health_check_imported_from_types_module():
    """Ensure ``HealthCheck`` is no longer defined inline in doctor_registry."""
    from yoke_core.engines import doctor_registry, doctor_registry_types

    assert doctor_registry.HealthCheck is doctor_registry_types.HealthCheck
