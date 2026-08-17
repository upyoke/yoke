"""Retained Yoke CLI adapters and their backing function ids.

The :class:`AdapterEntry` shape lives in
:mod:`service_client_structured_api_adapter_inventory_types`; the
installer, qa, and strategy family entries live in sibling modules
(350-cap split). This module concatenates the family lists into the one
``CLI_ADAPTERS`` surface consumers read.
"""

from __future__ import annotations

from typing import Dict, List

from yoke_core.api.service_client_structured_api_adapter_inventory_installer import (
    INSTALLER_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_items import ITEMS_ADAPTERS
from yoke_core.api.service_client_structured_api_adapter_inventory_github_actions import (
    GITHUB_ACTIONS_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_epic import (
    EPIC_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_direct_workflows import (
    DIRECT_WORKFLOW_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_qa import (
    QA_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_sessions import (
    SESSION_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_strategy import (
    STRATEGY_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_test_machine import (
    TEST_MACHINE_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_ops import (
    OPS_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_project_structure import (
    PROJECT_STRUCTURE_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_projects import (
    PROJECT_ADAPTERS,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AGENT_PATH_VALUES,
    AdapterEntry,
    read_entry as _read_entry,
)
from yoke_core.api.service_client_structured_api_adapter_inventory_workflows import (
    WORKFLOW_ADAPTERS,
)

CLI_ADAPTERS: List[AdapterEntry] = [
    *EPIC_ADAPTERS,
    *DIRECT_WORKFLOW_ADAPTERS,
    AdapterEntry("db_claim.amend", "python3 -m yoke_core.api.service_client db-claim-amend", notes="unified DB-claim amendment"),
    AdapterEntry("db_claim.prose_check", "yoke db-claim prose-check (PREFIX-N | --stdin)", notes="prose-vs-claim; --stdin local"),
    *SESSION_ADAPTERS,
    *ITEMS_ADAPTERS,
    AdapterEntry(
        function_id="lifecycle.transition.execute",
        cli_invocation="yoke lifecycle transition YOK-N --to <next>",
        notes="Lifecycle status transitions ride on items.scalar.update",
        agent_path="skill-orchestrated",
        canonical_skill_invocation="/yoke advance YOK-N <next>",
        direct_use_caveat=(
            "skips finalize re-anchor, claim lifecycle, source=advance "
            "attribution, and finalize_evidence_bundle."
        ),
    ),
    AdapterEntry(
        function_id="lifecycle.repair_status.execute",
        cli_invocation=(
            "yoke lifecycle repair-status YOK-N --to STATUS "
            "--reason TEXT"
        ),
        notes="operator-only audited lifecycle reconciliation",
    ),
    AdapterEntry("lifecycle.skip.record_recoverable_substrate", "yoke lifecycle skip record-recoverable-substrate YOK-N --chain-step N --project P --routed-action ACTION --failure-class CLASS --remediation-owner YOK-N"),
    # qa-family entries live in the _qa sibling module (350-cap split).
    *QA_ADAPTERS,
    *TEST_MACHINE_ADAPTERS,
    # Cross-family readers (db_router forms stay operator-debug).
    _read_entry(function_id="events.tail.run", cli_invocation="yoke events tail --limit N"),
    _read_entry(function_id="events.count.run", cli_invocation="yoke events count --event-name NAME"),
    _read_entry(function_id="events.anomalies.run", cli_invocation="yoke events anomalies --limit N"),
    _read_entry(function_id="claims.path.list", cli_invocation="yoke claims path list --item PREFIX-N"),
    _read_entry(function_id="claims.path.get", cli_invocation="yoke claims path get CLAIM_ID"),
    _read_entry(function_id="ouroboros.entry.list", cli_invocation="yoke ouroboros entry list --limit N"),
    _read_entry(function_id="ouroboros.entry.get", cli_invocation="yoke ouroboros entry get ENTRY_ID"),
    _read_entry(function_id="ouroboros.field_note.list", cli_invocation="yoke ouroboros field-note list --limit N"),
    _read_entry(function_id="ouroboros.field_note.get", cli_invocation="yoke ouroboros field-note get NOTE_ID"),
    _read_entry(function_id="projects.list", cli_invocation="yoke projects list"),
    *PROJECT_ADAPTERS,
    _read_entry(function_id="organizations.get", cli_invocation="yoke organizations get"),
    # Sign-in admission admin family (org-admin-gated at dispatch).
    AdapterEntry(
        function_id="identity.invite.create",
        cli_invocation="yoke identity invite create EMAIL --role ROLE",
        notes="pending invite admits the next verified OIDC sign-in with that email",
    ),
    _read_entry(function_id="identity.invite.list", cli_invocation="yoke identity invite list --status pending"),
    AdapterEntry(function_id="identity.invite.revoke", cli_invocation="yoke identity invite revoke INVITE_ID"),
    AdapterEntry(
        function_id="identity.link.set",
        cli_invocation="yoke identity link set --actor ACTOR --issuer I --subject S",
        notes="issuer+subject links directly; --email alone pre-links a future sign-in",
    ),
    AdapterEntry(function_id="identity.autojoin.set", cli_invocation="yoke identity autojoin set DOMAIN"),
    _read_entry(function_id="items.list.run", cli_invocation="yoke items list --status STATUS"),
    _read_entry(function_id="items.search.run", cli_invocation="yoke items search KEYWORDS"),
    _read_entry(function_id="db.read.run", cli_invocation='yoke db read "SELECT ..."'),
    _read_entry(function_id="shepherd.dependency_list.run", cli_invocation="yoke shepherd dependency-list PREFIX-N"),
    AdapterEntry(function_id="shepherd.verdict.run", cli_invocation="yoke shepherd verdict --item PREFIX-N --transition T --worker W --verdict V"),
    AdapterEntry(function_id="shepherd.caveat_disposition.run", cli_invocation="yoke shepherd caveat-disposition --item PREFIX-N --transition T --attempt N --caveat-num N --caveat-text TEXT --disposition RESOLVED"),
    AdapterEntry(
        function_id="claims.work.acquire",
        cli_invocation="python3 -m yoke_core.api.service_client claim-work",
        agent_path="skill-orchestrated",
        canonical_skill_invocation="/yoke advance YOK-N <next>",
        direct_use_caveat=(
            "inside lifecycle transitions, bypasses routed claim lifecycle "
            "events; direct use remains valid for non-lifecycle claim flows."
        ),
    ),
    AdapterEntry(
        function_id="claims.work.release",
        cli_invocation=(
            "python3 -m yoke_core.api.service_client release-work-claim"
        ),
        agent_path="skill-orchestrated",
        canonical_skill_invocation="/yoke advance YOK-N <next>",
        direct_use_caveat=(
            "inside lifecycle transitions, bypasses the structured handoff "
            "payload; direct use remains valid for non-lifecycle claim flows."
        ),
    ),
    AdapterEntry(
        function_id="claims.work.release_session_scoped",
        cli_invocation="yoke claims work release --all-mine",
        direct_use_caveat="agent surrenders every active claim; harness owns session-end.",
    ),
    _read_entry(
        function_id="claims.work.holder_get",
        cli_invocation=(
            "python3 -m runtime.harness.harness_sessions who-claims YOK-N"
        ),
    ),
    _read_entry(
        function_id="claims.work.holder_list",
        cli_invocation="python3 -m yoke_core.api.service_client path-claim-list",
    ),
    AdapterEntry(
        function_id="claims.path.register",
        cli_invocation=(
            "python3 -m yoke_core.api.service_client path-claim-register"
        ),
    ),
    AdapterEntry(
        function_id="claims.path.widen",
        cli_invocation="python3 -m yoke_core.api.service_client path-claim-widen",
    ),
    AdapterEntry(function_id="claims.path.amend", cli_invocation="yoke claims path amend --claim-id N --add-paths PATHS --reason TEXT --item PREFIX-N"),
    AdapterEntry(
        function_id="claims.path.release",
        cli_invocation=(
            "python3 -m yoke_core.api.service_client path-claim-release"
        ),
    ),
    AdapterEntry(
        function_id="claims.path.override",
        cli_invocation=(
            "yoke claims path override --claim-id N "
            "--override-point creation --integration-target main "
            "--actor-id N --actor-reason TEXT"
        ),
    ),
    AdapterEntry(
        function_id="claims.path.activation_run",
        cli_invocation=(
            "python3 -m yoke_core.cli.db_router path-claims activation-run"
        ),
    ),
    AdapterEntry(
        function_id="claims.path.coordination_decision_build",
        cli_invocation=(
            "yoke claims path coordination-decision-build"
        ),
    ),
    AdapterEntry(
        function_id="claims.coordination_lease.acquire",
        cli_invocation=(
            "python3 -m yoke_core.api.service_client coordination-lease-acquire"
        ),
    ),
    AdapterEntry(
        function_id="claims.coordination_lease.heartbeat",
        cli_invocation=(
            "python3 -m yoke_core.api.service_client coordination-lease-heartbeat"
        ),
    ),
    AdapterEntry(
        function_id="claims.coordination_lease.release",
        cli_invocation=(
            "python3 -m yoke_core.api.service_client coordination-lease-release"
        ),
    ),
    AdapterEntry(
        function_id="claims.coordination_lease.list",
        cli_invocation=(
            "python3 -m yoke_core.api.service_client coordination-lease-list"
        ),
    ),
    *PROJECT_STRUCTURE_ADAPTERS,
    *STRATEGY_ADAPTERS,
    # Operational families wrapped by the registry_* sub-modules (deployment,
    # readiness, shepherd-dependency, ephemeral-env, strategy-carry/checkpoint,
    # events/ouroboros) + onboard-checklist; parity-synced into the inventory.
    *OPS_ADAPTERS,
    *GITHUB_ACTIONS_ADAPTERS,
    AdapterEntry(
        function_id="github.pr.create",
        cli_invocation=(
            "yoke github pr create --title TITLE --head BRANCH "
            "--project <project> [--base BRANCH] "
            "[--body TEXT | --body-stdin] [--draft]"
        ),
        notes="bearer-token PR create; repo resolves from project capability.",
    ),
    AdapterEntry(
        function_id="github.release.create_next_tag",
        cli_invocation=(
            "yoke github release create-next-tag OWNER/REPO SOURCE-SHA "
            "--summary TEXT --project P"
        ),
        notes=(
            "Creates or recovers the next immutable annotated launch tag "
            "through the project's scoped GitHub App authority."
        ),
    ),
    _read_entry(
        function_id="items.get.run",
        cli_invocation=(
            "python3 -m yoke_core.cli.db_router items get YOK-N <field>"
        ),
    ),
    _read_entry(
        function_id="events.query.run",
        cli_invocation="python3 -m yoke_core.cli.db_router events list",
    ),
    _read_entry(
        function_id="path_claims.conflicts.list",
        cli_invocation=(
            "python3 -m yoke_core.cli.db_router path-claims conflicts-list"
        ),
    ),
    _read_entry(
        function_id="doctor.run.run",
        cli_invocation="python3 -m yoke_core.engines.doctor",
    ),
    _read_entry(
        function_id="doctor.last_run.get",
        cli_invocation="yoke doctor last-run get [--project P]",
        notes=(
            "Reads the newest completed doctor run from the events journal; "
            "doctor findings persist nowhere else."
        ),
    ),
    *WORKFLOW_ADAPTERS,
    *INSTALLER_ADAPTERS,
    AdapterEntry(function_id="board.rebuild.run", cli_invocation="yoke board rebuild"),
    _read_entry(
        function_id="board.data.get",
        cli_invocation="yoke board data get [--scope NAME]",
        notes=(
            "Server half of the board rebuild composition: returns the "
            "recorded query plan; rendering and file writes stay client-side."
        ),
    ),
    _read_entry(
        function_id="lint.config.show",
        cli_invocation="yoke lint config show [--root PATH]",
        notes=(
            "Reports the resolved .yoke/lint-config, how its root was chosen, "
            "and each guard's effective mode, including a protected-guard warn "
            "clamped back to deny for a missing allow-warn token."
        ),
    ),
    AdapterEntry(
        function_id="hook.evaluate.run",
        cli_invocation="yoke hook evaluate <event> [--dry-run]",
    ),
    AdapterEntry(
        function_id="packets.render.run",
        cli_invocation=(
            "python3 -m yoke_core.domain.schema_api_context render"
        ),
    ),
    _read_entry(
        function_id="packets.check.run",
        cli_invocation=(
            "python3 -m yoke_core.domain.schema_api_context check"
        ),
    ),
    AdapterEntry(
        function_id="agents.render.run",
        cli_invocation="python3 -m yoke_core.domain.agents_render render",
    ),
    _read_entry(
        function_id="agents.render.check",
        cli_invocation="python3 -m yoke_core.domain.agents_render check",
    ),
    AdapterEntry("ouroboros.field_note.append", "python3 -m yoke_core.api.service_client field-note-log"),
    _read_entry(function_id="scratch.dispatch_inputs", cli_invocation="yoke scratch dispatch-inputs <YOK-N|item-id> <session_id> <attempt>", notes="Helper-resolved dispatch-inputs path; wraps yoke_cli.commands.adapters.misc.scratch_dispatch_inputs."),
]

def adapter_index() -> Dict[str, AdapterEntry]:
    return {entry.function_id: entry for entry in CLI_ADAPTERS}


def _taught_adapters() -> List[AdapterEntry]:
    """Lazy import of the taught-adapter sibling."""
    try:
        from yoke_core.api.service_client_structured_api_adapter_inventory_taught import (
            TAUGHT_ADAPTERS,
        )
    except Exception:
        return []
    return list(TAUGHT_ADAPTERS)


def all_adapter_entries() -> List[AdapterEntry]:
    """Return registered + taught adapter entries (lint consumer)."""
    return list(CLI_ADAPTERS) + _taught_adapters()


__all__ = ["AGENT_PATH_VALUES", "AdapterEntry", "CLI_ADAPTERS", "adapter_index", "all_adapter_entries"]
