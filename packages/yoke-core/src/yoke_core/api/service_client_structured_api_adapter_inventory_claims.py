"""Adapter inventory entries for registered claim families."""

from __future__ import annotations

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry,
)


CLAIMS_ADAPTERS = [
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
        cli_invocation=("python3 -m yoke_core.api.service_client release-work-claim"),
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
        direct_use_caveat=(
            "agent surrenders every active claim; harness owns session-end."
        ),
    ),
    read_entry(
        function_id="claims.work.holder_get",
        cli_invocation="python3 -m yoke_core.hooks.sessions_cli who-claims YOK-N",
    ),
    read_entry(
        function_id="claims.work.holder_list",
        cli_invocation="python3 -m yoke_core.api.service_client path-claim-list",
    ),
    AdapterEntry(
        "claims.path.register",
        "python3 -m yoke_core.api.service_client path-claim-register",
    ),
    AdapterEntry(
        "claims.path.widen",
        "python3 -m yoke_core.api.service_client path-claim-widen",
    ),
    AdapterEntry(
        function_id="claims.path.amend",
        cli_invocation=(
            "yoke claims path amend --claim-id N "
            "(--add-paths PATHS | --remove-paths PATHS) --reason TEXT "
            "--item PREFIX-N [--integration-target BRANCH]"
        ),
    ),
    AdapterEntry(
        "claims.path.release",
        "python3 -m yoke_core.api.service_client path-claim-release",
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
        "claims.path.activation_run",
        "python3 -m yoke_core.cli.db_router path-claims activation-run",
    ),
    AdapterEntry(
        "claims.path.coordination_decision_build",
        "yoke claims path coordination-decision-build",
    ),
    AdapterEntry(
        "claims.coordination_lease.acquire",
        "python3 -m yoke_core.api.service_client coordination-lease-acquire",
    ),
    AdapterEntry(
        "claims.coordination_lease.heartbeat",
        "python3 -m yoke_core.api.service_client coordination-lease-heartbeat",
    ),
    AdapterEntry(
        "claims.coordination_lease.release",
        "python3 -m yoke_core.api.service_client coordination-lease-release",
    ),
    AdapterEntry(
        "claims.coordination_lease.list",
        "python3 -m yoke_core.api.service_client coordination-lease-list",
    ),
    AdapterEntry(
        "claims.steering.acquire",
        "yoke claims steering acquire --project P [--reason TEXT]",
    ),
    AdapterEntry(
        "claims.steering.release",
        "yoke claims steering release CLAIM_ID --reason TEXT",
    ),
    read_entry(
        function_id="claims.steering.list",
        cli_invocation=(
            "yoke claims steering list [--project P] [--session-id S] [--active-only]"
        ),
    ),
]


__all__ = ["CLAIMS_ADAPTERS"]
