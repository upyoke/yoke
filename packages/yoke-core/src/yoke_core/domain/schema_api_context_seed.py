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
    "AGENT_WRITE_FUNCTION_IDS",
    "PACKET_LINE_BUDGET_PER_ROLE",
    "PACKET_LINE_BUDGET_AGGREGATE",
    "PACKET_BYTE_BUDGET_PER_ROLE",
    "PACKET_BYTE_BUDGET_AGGREGATE",
    "AGENT_PROMPT_BYTE_BUDGET",
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
    "claim_session_id",
    "item_claims",
    "work_claims.target_id",
    "qa_kind='review'",
    "--qa-kind review",
    ".agents/skills/yoke/scripts/python3 -m " + "yoke_core.cli.db_router qa",
    "blocker_item_id",
)


# ---------------------------------------------------------------------------
# Per-role topic assignments. Each LLM-facing Yoke agent receives the
# union of their topic packets in render order.
#
# Role/topic doctrine:
# - ``main_agent`` is the top-level Yoke agent running inline skills /
#   ad-hoc investigation. It receives ``core`` + ``claims`` plus ``qa`` and
#   the compact Pack projection topic;
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
# - ``engineer_agent`` / ``tester_agent`` / ``qa_walker_agent`` add ``qa``
#   and ``project`` for
#   QA discovery, gate previews, and project test command surfacing. The
#   rationale is mirrored in ``docs/agents.md``.
#
# Role names are layer-explicit (``*_agent``) so they cannot be confused
# with the harness manifest / bootstrap substrate contract, which is
# documented separately under the ``harness_contract`` packet name and
# is deliberately NOT a ``schema_api_context`` role.
# ---------------------------------------------------------------------------

ROLE_TOPICS: dict[str, tuple[str, ...]] = {
    "main_agent": ("core", "claims", "auth", "qa", "packs"),
    "architect_agent": ("core", "claims"),
    "engineer_agent": ("core", "claims", "qa", "project"),
    "tester_agent": ("core", "claims", "qa", "project"),
    "qa_walker_agent": ("core", "claims", "qa", "project"),
    "simulator_agent": ("core", "claims"),
    "boss_agent": ("core", "claims"),
}


# The registered write function ids every packet names. They are the shape an
# agent dispatches through, so they belong in the compact body beside the table
# and column names: a confabulated function id fails exactly like a
# confabulated column, and both used to live only in the long-form notes.
# ``doctor_registry_tier_discipline`` requires the packet to enumerate them.
AGENT_WRITE_FUNCTION_IDS: tuple[str, ...] = (
    "items.structured_field.replace",
    "items.progress_log.append",
    "lifecycle.transition.execute",
    "claims.work.acquire",
    "claims.work.release",
    "claims.path.register",
    "db_claim.amend",
)


# Topics that exist (for validator + CLI flag completion).
TOPICS: tuple[str, ...] = ("core", "claims", "auth", "qa", "project", "packs")


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
        # The satisfier-ladder substrate: how a gate obligation was
        # actually discharged for an item, and the derived project
        # facts that pick the rung.
        "item_gate_satisfactions",
        "project_derived_facts",
        # Python helper surfaces — not SQL tables, but rendered alongside
        # the schema cheat sheet so agents learn the Postgres-native DB router
        # path and `db_helpers.connect()` signature without confabulating wrong
        # import names.
        "yoke_core.domain.worktree",
        "yoke_core.domain.db_helpers",
        "yoke_contracts.model_reference",
        # The harness capability authority. Every role gets `core`, so no
        # agent has to discover from prose that manifests, not documents,
        # decide what a harness can do.
        "runtime/harness/<harness_id>/manifest.json",
    ),
    "claims": (
        "harness_sessions",
        "session_tool_calls",
        "work_claims",
        "path_claims",
        "path_claim_targets",
        "path_claim_task_bindings",
        "path_targets",
        "path_claim_amendments",
        "actors",
        "machines",
        "harness_machine_reports",
    ),
    "auth": (
        "roles",
        "permissions",
        "role_permissions",
        "actor_project_roles",
        "organizations",
        "actor_org_roles",
    ),
    "qa": ("qa_requirements", "qa_runs", "doctor_runs"),
    "packs": (
        "pack_catalog",
        "project_pack_reports",
        "project_pack_report_entries",
    ),
    "project": (
        "projects",
        "project_structure",
        "deployment_flows",
        "deployment_runs",
        "deployment_run_items",
        "path_snapshots",
        "project_capabilities",
        "capability_secrets",
        "github_app_installations",
        "project_github_repo_bindings",
        "migration_audit",
    ),
}


# Ratchet budgets for the rendered packet corpus. Every number is the
# measured size of the compact body that ships today, rounded up to a round
# figure so ordinary editing does not trip the gate — not a prose target, and
# not a claim about where any harness truncates. Growth past one of these is
# a decision with a number attached rather than a drift back toward an
# undeliverable payload.
#
# Two axes, because one of them bounds nothing that matters on its own. A
# packet can sit under a line cap while spending six figures of bytes, since
# nothing stops a single line from carrying thousands; the byte axis is what
# a delivery channel measures. Lines stay budgeted because they keep the
# rendered body readable.
#
# Per-role and aggregate line budgets cover the compact body's table and
# command listings — every table, every column name, and every registered
# recipe. The long-form per-table and per-command notes are rendered only at
# ``--detail full``, read deliberately at the moment they apply, and carry no
# budget at all.
PACKET_LINE_BUDGET_PER_ROLE: int = 340
PACKET_LINE_BUDGET_AGGREGATE: int = 2100
PACKET_BYTE_BUDGET_PER_ROLE: int = 32000
PACKET_BYTE_BUDGET_AGGREGATE: int = 196000

# Ratchet budget for one rendered subagent body: the condensed role prose
# plus its compact packet. A subagent body is read from a file rather than
# composed into a hook reply, so no observed truncation point bounds it —
# this is purely the measured figure that keeps it from regrowing. Measured:
# the largest body spends 58,981 bytes, down from 168,187 when every role
# carried the full packet plus its conditional references inline.
AGENT_PROMPT_BYTE_BUDGET: int = 60000
