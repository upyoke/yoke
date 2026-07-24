"""Shared foundation for the tier-discipline doctor HC family.

Yoke's teaching surfaces are organized into seven tiers (substrate
disciplines, auto-loaded packets, orientation, reference catalogs,
canonical agent bodies, skill prose, per-skill subdocs). Structural
truth — table/column names, CLI shapes, enum values — lives in Tier 1
(the auto-loaded packet) only; Tiers 0/2/4/5 reach Tier 1 via sanctioned
cross-references rather than restating schema facts.

This module owns the shared data + helpers every tier-discipline HC
consumes, plus the registry bundle (`TIER_DISCIPLINE_HEALTH_CHECKS`)
spliced into `doctor_registry.HEALTH_CHECKS`. The module is pure data
plus pure helpers: no DB access, no I/O beyond `pathlib.Path.glob`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Tuple


# Canonical tier -> path-glob mapping. Globs are repo-relative; callers
# resolve them against the repo root via `iter_tier_paths`. Tier 6
# (archive) is exempt by default from bleed scanning; `iter_tier_paths`
# also skips any file under TIER_6_ARCHIVE_PREFIXES regardless of which
# tier's glob matched it.
TIER_GLOBS: dict[int, tuple[str, ...]] = {
    # Tier 0 — substrate disciplines, auto-loaded into every session prompt.
    0: (
        "AGENTS.md",
        "runtime/harness/claude/rules/session.md",
        "docs/prompt-philosophy.md",
    ),
    # Tier 2 — orientation docs, read on demand.
    2: (
        "docs/OVERVIEW.md",
        ".yoke/docs/lifecycle.md",
        ".yoke/docs/commands.md",
        "docs/harness-substrate.md",
        "docs/harness-bootstrap.md",
    ),
    # Tier 4 — canonical agent bodies. Rendered harness adapters derive
    # from these and are not scanned independently.
    4: (
        "runtime/agents/*.md",
    ),
    # Tier 5 — skill prose (top-level SKILL.md plus skill-internal subdocs).
    5: (
        ".agents/skills/yoke/*/SKILL.md",
        ".agents/skills/yoke/*/*.md",
    ),
    # Tier 6 — archive decision records (callers opt in explicitly).
    6: (
        "docs/archive/**/*.md",
    ),
}


# Sanctioned cross-reference openings. A line containing one of these
# prefixes is treated as a legitimate cite-toward-Tier-1 / -Tier-3
# reference and exempted from bleed scanning.
CROSS_REFERENCE_PREFIXES: tuple[str, ...] = (
    "see your `",
    "see the `",
)


# Archive-root prefixes — repo-relative paths starting with any entry
# here are exempt by default from every tier-discipline HC.
TIER_6_ARCHIVE_PREFIXES: tuple[str, ...] = (
    "docs/archive/",
)


# Tier 1 — the in-memory rendered `schema_api_context` packet (no
# filesystem surface, hence the empty tuple).
TIER_1_GLOBS: tuple[str, ...] = ()


# Tier 3 — reference catalogs. The truth target every Tier 0/2/4/5
# cross-reference points at.
TIER_3_GLOBS: tuple[str, ...] = (
    "docs/atlas.md",
    "docs/event-catalog.md",
    ".yoke/docs/db-reference.md",
    ".yoke/docs/db-reference/*.md",
    "docs/state-management.md",
    ".yoke/docs/charge-frontier.md",
)


# Function ids every `*_agent` packet must enumerate. Consumed by
# HC-packet-tier-completeness + HC-progressive-disclosure-direction.
REQUIRED_FUNCTION_IDS: tuple[str, ...] = (
    "items.structured_field.replace",
    "claims.work.acquire",
    "claims.work.release",
    "claims.path.register",
    "items.progress_log.append",
    "lifecycle.transition.execute",
    "db_claim.amend",
)


def _is_archive_path(rel_path: str) -> bool:
    """Return True when `rel_path` lives under a Tier 6 archive root."""

    return any(rel_path.startswith(prefix) for prefix in TIER_6_ARCHIVE_PREFIXES)


def iter_tier_paths(
    repo_root: Path,
    tiers: Iterable[int] = (0, 2, 4, 5),
) -> Iterator[Tuple[int, Path]]:
    """Yield (tier, absolute path) for every file in the scanned tiers.

    Iteration order is stable: tiers in the order supplied by the
    caller (default ``(0, 2, 4, 5)``), and within each tier the
    sorted-by-path globs followed by sorted match results. Files under
    `TIER_6_ARCHIVE_PREFIXES` are skipped regardless of which tier's
    glob matched them (defense in depth for the archive exemption).
    Duplicate paths matched by multiple globs in the same tier are
    yielded once per tier (first match wins).
    """

    repo_root = Path(repo_root)
    for tier in tiers:
        globs = TIER_GLOBS.get(tier)
        if not globs:
            continue
        seen: set[Path] = set()
        for pattern in globs:
            for match in sorted(repo_root.glob(pattern)):
                if not match.is_file():
                    continue
                rel = match.relative_to(repo_root).as_posix()
                if _is_archive_path(rel):
                    continue
                if match in seen:
                    continue
                seen.add(match)
                yield tier, match


def is_cross_reference_line(line: str) -> bool:
    """Return True if `line` contains a sanctioned cross-reference prefix.

    Substring match (case-sensitive): any occurrence of an entry from
    `CROSS_REFERENCE_PREFIXES` anywhere in the line counts. The
    prefixes are deliberately narrow (the backtick-led packet-stanza
    form) so the allow-list does not silently exempt unrelated prose.
    """

    return any(prefix in line for prefix in CROSS_REFERENCE_PREFIXES)


# Registry bundle — spliced into doctor_registry.HEALTH_CHECKS via
# `HEALTH_CHECKS.extend(...)` in stable order. Sibling-bundle pattern
# mirrors COORDINATION_HEALTH_CHECKS / ARCHITECTURE_HEALTH_CHECKS. HC
# functions are imported via PEP-562 module `__getattr__` to avoid the
# circular-import path (each HC module imports the constants above).
from yoke_core.engines.doctor_registry_types import HealthCheck  # noqa: E402


_TIER_DISCIPLINE_HEALTH_CHECKS: Optional[List[HealthCheck]] = None


def _build_health_checks() -> List[HealthCheck]:
    global _TIER_DISCIPLINE_HEALTH_CHECKS
    if _TIER_DISCIPLINE_HEALTH_CHECKS is not None:
        return _TIER_DISCIPLINE_HEALTH_CHECKS
    from yoke_core.engines.doctor_hc_cli_help_handler import hc_cli_help_handler_present  # noqa: E501
    from yoke_core.engines.doctor_hc_packet_tier_completeness import hc_packet_tier_completeness  # noqa: E501
    from yoke_core.engines.doctor_hc_progressive_disclosure_direction import hc_progressive_disclosure_direction  # noqa: E501
    from yoke_core.engines.doctor_hc_tier_cli_shape_bleed import hc_tier_cli_shape_bleed
    from yoke_core.engines.doctor_hc_tier_module_path_resolution import hc_tier_module_path_resolution  # noqa: E501
    from yoke_core.engines.doctor_hc_tier_schema_bleed import hc_tier_schema_bleed

    _TIER_DISCIPLINE_HEALTH_CHECKS = [
        HealthCheck("tier-schema-bleed", "Tier 0/2/4/5 surfaces restate Tier 1 schema facts", hc_tier_schema_bleed),  # noqa: E501
        HealthCheck("tier-cli-shape-bleed", "Tier 0/2/4/5 surfaces teach drifted CLI shape or bare doctor", hc_tier_cli_shape_bleed),  # noqa: E501
        HealthCheck("packet-tier-completeness", "Skill prose names a column the main_agent packet does not list", hc_packet_tier_completeness),  # noqa: E501
        HealthCheck("progressive-disclosure-direction", "Backward tier citation or vague denial without concrete function id", hc_progressive_disclosure_direction),  # noqa: E501
        HealthCheck("tier-module-path-resolution", "Tier 0/2/4/5 surface cites a runtime.api.* module that does not resolve", hc_tier_module_path_resolution),  # noqa: E501
        HealthCheck("cli-help-handler-present", "Every service_client subcommand exits 0 on --help", hc_cli_help_handler_present),  # noqa: E501
    ]
    return _TIER_DISCIPLINE_HEALTH_CHECKS


def __getattr__(name: str):
    if name == "TIER_DISCIPLINE_HEALTH_CHECKS":
        return _build_health_checks()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
