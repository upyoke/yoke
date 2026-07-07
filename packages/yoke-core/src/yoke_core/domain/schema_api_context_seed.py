"""Curated schema/API facts consumed by ``schema_api_context``.

Single source of truth for the agent-facing DB Quick Reference packet
content. The packet generator (:mod:`yoke_core.domain.schema_api_context`)
prefers live catalog introspection plus CLI ``--help`` parsing at packet-build
time, but falls back to this curated seed when the live DB is unavailable
(fresh checkout, broken bootstrap state).

The seed is also the cross-check the generator uses to detect drift: if
live introspection yields a column that contradicts the curated row the
renderer fails so the seed gets updated rather than silently shipping
stale agent context.

Pure data only — no I/O and no DB connections. The facade imports only
its sibling seed-data modules.

Layout: this module is the facade. The two largest data structures
(:data:`CANONICAL_TABLES` and :data:`WRAPPER_COMMANDS`) live in sibling
modules so the facade itself stays small and readable.
"""

from __future__ import annotations

from yoke_core.domain.schema_api_context_commands import WRAPPER_COMMANDS
from yoke_core.domain.schema_api_context_tables import CANONICAL_TABLES


__all__ = [
    "CANONICAL_TABLES",
    "WRAPPER_COMMANDS",
    "STALE_TERMS",
    "ROLE_TOPICS",
    "TOPICS",
    "TOPIC_TABLES",
    "PACKET_LINE_BUDGET_PER_ROLE",
    "PACKET_LINE_BUDGET_AGGREGATE",
]


# ---------------------------------------------------------------------------
# Stale-name absence regression — wrong terms an audit must verify never
# appear in any rendered packet body or canonical / rendered Bash-capable
# agent prompt. Concatenated string literals keep the bare wrong name out
# of this file's grep surface (defense in depth alongside the runtime
# tests that build the full strings at import time).
# ---------------------------------------------------------------------------

STALE_TERMS: tuple[str, ...] = (
    # NOTE: `owner_session_id` is a real path_claims column carrying
    # typed session-owned authority — do not add it back to STALE_TERMS.
    "claim_" "session_id",
    "item_" "claims",
    "work_claims" ".target_id",
    "command_definitions" " WHERE",
    "qa_kind=" "'review'",
    "--qa-kind " "review",
    ".agents/skills/yoke/" "scripts/python3 -m yoke_core.cli.db_router qa",
    "blocker_" "item_id",
)


# ---------------------------------------------------------------------------
# Per-role topic assignments. Each LLM-facing Yoke agent receives the
# union of their topic packets in render order.
#
# Role/topic doctrine:
# - ``main_agent`` is the top-level Yoke agent running inline skills /
#   ad-hoc investigation. It receives ``core`` + ``claims`` plus ``qa``;
#   deployment-run raw-query diagnostics are taught as a compact role hint
#   so the main packet does not inherit the full project topic:
#   conduct / polish / advance main sessions orchestrate engineer +
#   tester loops and routinely inspect tester-review state ahead of
#   re-dispatch, so the ``qa_requirements`` / ``qa_runs`` surface
#   belongs in the main-session packet rather than only in the
#   engineer / tester sub-packets. Without it the main session
#   confabulates plausible ``epic_*``-shaped names (e.g. ``epic_reviews``)
#   that do not exist.
# - ``architect_agent`` / ``simulator_agent`` / ``boss_agent`` carry
#   ``core`` + ``claims``: they plan, trace, and verdict against the same
#   spine but never record QA runs and never invoke project test commands
#   directly.
# - ``engineer_agent`` / ``tester_agent`` add ``qa`` and ``project`` for
#   QA discovery, gate previews, and project test command surfacing. The
#   rationale is mirrored in ``docs/agents.md``.
#
# Role names are layer-explicit (``*_agent``) so they cannot be confused
# with the harness manifest / bootstrap substrate contract, which is
# documented separately under the ``harness_contract`` packet name and
# is deliberately NOT a ``schema_api_context`` role.
# ---------------------------------------------------------------------------

ROLE_TOPICS: dict[str, tuple[str, ...]] = {
    "main_agent": ("core", "claims", "auth", "qa"),
    "architect_agent": ("core", "claims"),
    "engineer_agent": ("core", "claims", "qa", "project"),
    "tester_agent": ("core", "claims", "qa", "project"),
    "simulator_agent": ("core", "claims"),
    "boss_agent": ("core", "claims"),
}


# Topics that exist (for validator + CLI flag completion).
TOPICS: tuple[str, ...] = ("core", "claims", "auth", "qa", "project")


# Tables surfaced by topic. Every fact in the packet derives from this map.
TOPIC_TABLES: dict[str, tuple[str, ...]] = {
    "core": (
        "items",
        "epic_tasks",
        "epic_dispatch_chains",
        "epic_progress_notes",
        "item_dependencies",
        "events",
        "event_registry",
        "ouroboros_entries",
        "item_sections",
        # Python helper surfaces — not SQL tables, but rendered alongside
        # the schema cheat sheet so agents learn the Postgres-native DB router
        # path and `db_helpers.connect()` signature without confabulating wrong
        # import names.
        "yoke_core.domain.worktree",
        "yoke_core.domain.db_helpers",
    ),
    "claims": (
        "harness_sessions",
        "session_tool_calls",
        "work_claims",
        "path_claims",
        "path_claim_targets",
        "path_targets",
        "path_claim_amendments",
        "actors",
        "actor_labels",
    ),
    "auth": (
        "roles",
        "permissions",
        "role_permissions",
        "actor_project_roles",
        "organizations",
        "actor_org_roles",
    ),
    "qa": ("qa_requirements", "qa_runs"),
    "project": (
        "projects",
        "project_structure",
        "deployment_flows",
        "deployment_runs",
        "deployment_run_items",
        "path_snapshots",
        "project_capabilities",
        "capability_secrets",
        "migration_audit",
    ),
}


# Tests fail when a rendered packet exceeds its budget — curate rather
# than duplicate. Per-role budget covers each `*_agent` packet; aggregate
# budget covers all six roles combined. The budgets absorb the inline
# universal recipe set (cancel/transition, progress-log via HTTP,
# function-call envelope dispatch, session lifecycle, field-note
# channel, claim/path-claim concrete-value variants); the recipes ARE the
# value the packet exists to deliver. They also cover the concrete
# `items get` example, github_issue resolution, SELECT-query
# self-orientation, and the cold-start helper that replaces the verbose
# lifecycle entry. The watcher / Monitor / background-command recipes
# pasted into the ``schema_api_context_commands_watchers`` sibling — the
# vetted-telemetry watch_pytest / watch_doctor / watch_merge patterns —
# push each multi-topic packet (engineer_agent / tester_agent) past a
# smaller per-role cap, so the cap follows the recipes the packet now
# carries.
PACKET_LINE_BUDGET_PER_ROLE: int = 410
PACKET_LINE_BUDGET_AGGREGATE: int = 2150
