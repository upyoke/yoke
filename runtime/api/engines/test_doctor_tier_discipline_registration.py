"""Registration of project-owned tier-discipline checks."""

from __future__ import annotations

from pathlib import Path

from yoke_project_checks import check_packet_tier_completeness as packet_mod
from yoke_project_checks import check_progressive_disclosure_direction as disc_mod
from yoke_project_checks import check_tier_cli_shape_bleed as cli_mod
from yoke_project_checks import check_tier_module_path_resolution as mod_path_mod
from yoke_project_checks import check_tier_schema_bleed as schema_mod
from yoke_core.engines.doctor_project_checks import discover_project_checks
from yoke_core.engines.doctor_registry_tier_discipline import (
    TIER_DISCIPLINE_HEALTH_CHECKS,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

_TIER_DISCIPLINE_CHECK_FUNCTIONS = {
    "tier-schema-bleed": schema_mod.hc_tier_schema_bleed,
    "tier-cli-shape-bleed": cli_mod.hc_tier_cli_shape_bleed,
    "packet-tier-completeness": packet_mod.hc_packet_tier_completeness,
    "progressive-disclosure-direction": disc_mod.hc_progressive_disclosure_direction,
    "tier-module-path-resolution": mod_path_mod.hc_tier_module_path_resolution,
}


def test_tier_discipline_checks_registered_as_project_checks():
    assert [hc.slug for hc in TIER_DISCIPLINE_HEALTH_CHECKS] == []
    checks = discover_project_checks(REPO_ROOT).checks
    slugs = [hc.slug for hc in checks]
    by_slug = {hc.slug: hc for hc in checks}
    for slug, fn in _TIER_DISCIPLINE_CHECK_FUNCTIONS.items():
        assert slugs.count(slug) == 1, (
            f"slug {slug!r} appears {slugs.count(slug)} times in the checks "
            f"discovered under {REPO_ROOT}"
        )
        registered = by_slug[slug].fn
        assert (registered.__module__, registered.__name__) == (
            fn.__module__,
            fn.__name__,
        )
