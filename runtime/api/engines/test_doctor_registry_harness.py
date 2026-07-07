"""Tests for the harness/session + substrate-parity health-check bundle.

Combines task 13's session/harness coverage with task 10's substrate-parity
coverage. The bundle module exposes ``HARNESS_HEALTH_CHECKS`` as a constant.
"""

from __future__ import annotations

from yoke_core.engines.doctor_registry_harness import HARNESS_HEALTH_CHECKS
from yoke_core.engines.doctor_registry_types import HealthCheck


# Group A — task 13 (session/harness substrate)
_GROUP_A_SLUGS = (
    "stale-sessions",
    "stale-session-reclaimer-alive",
    "stale-reclaim-collision",
    "session-startup-hook",
    "browser-substrate",
    "session-cwd-binding",
    "session-pre-implementing-activity",
    "session-lane-mismatch",
)

# Group B — task 10 (harness substrate parity HCs, appended after Group A)
_GROUP_B_SLUGS = (
    "harness-substrate-drift",
    "codex-hook-matchers",
    "codex-hook-floor",
    "codex-hook-doc-drift",
    "apply-patch-deny-smoke",
    "apply-patch-observe-smoke",
    "codex-agent-adapter-drift",
    "codex-subagent-surface-truth",
    "path-claim-bash-guard",
)

# Group C — ledger-audit HCs (cross-session mutation evidence)
_GROUP_C_SLUGS = (
    "claim-boundary-audit",
    "event-outcome-enum-coverage",
    "executor-canonicalization",
)

# Group D — reflection-capture hook coverage + persist-failed audit HCs
_GROUP_D_SLUGS = (
    "reflection-capture-hook-coverage",
    "reflection-capture-unhandled",
    "reflection-capture-persist-failed",
)


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


def test_bundle_holds_group_a_then_group_b_in_order():
    """Group A (task 13) precedes Group B (task 10), then Group C audit HCs."""
    slugs = [hc.slug for hc in HARNESS_HEALTH_CHECKS]
    assert slugs == (
        list(_GROUP_A_SLUGS)
        + list(_GROUP_B_SLUGS)
        + list(_GROUP_C_SLUGS)
        + list(_GROUP_D_SLUGS)
    )


def test_each_substrate_parity_slug_registered_exactly_once():
    """AC-2: task 10's 9 entries appear exactly once in the bundle."""
    slugs = [hc.slug for hc in HARNESS_HEALTH_CHECKS]
    for slug in _GROUP_B_SLUGS:
        assert slugs.count(slug) == 1, (
            f"slug {slug!r} appears {slugs.count(slug)} times in HARNESS_HEALTH_CHECKS"
        )


def test_substrate_parity_checks_use_canonical_dataclass_and_are_not_github_dependent():
    """Task 10's substrate parity checks are local-only (no github_dependent)."""
    by_slug = {hc.slug: hc for hc in HARNESS_HEALTH_CHECKS}
    for slug in _GROUP_B_SLUGS:
        hc = by_slug[slug]
        assert isinstance(hc, HealthCheck)
        assert callable(hc.fn)
        assert hc.github_dependent is False


def test_session_cwd_binding_id_unique_in_full_registry():
    """AC-8: HC-session-cwd-binding does not collide with any other HC."""
    from yoke_core.engines.doctor_registry import HEALTH_CHECKS

    matches = [hc for hc in HEALTH_CHECKS if hc.slug == "session-cwd-binding"]
    assert len(matches) == 1


def test_full_registry_slugs_remain_unique():
    from yoke_core.engines.doctor_registry import HEALTH_CHECKS

    slugs = [hc.slug for hc in HEALTH_CHECKS]
    assert len(set(slugs)) == len(slugs), (
        "duplicate slugs in HEALTH_CHECKS: "
        f"{[s for s in slugs if slugs.count(s) > 1]}"
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
    last_n = slugs[-len(bundle_slugs):]
    assert last_n == bundle_slugs


def test_health_check_imported_from_types_module():
    """Ensure ``HealthCheck`` is no longer defined inline in doctor_registry."""
    from yoke_core.engines import doctor_registry, doctor_registry_types

    assert doctor_registry.HealthCheck is doctor_registry_types.HealthCheck
