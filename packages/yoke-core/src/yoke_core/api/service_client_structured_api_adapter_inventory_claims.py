"""Adapter inventory entries for registered claim families."""

from __future__ import annotations

from yoke_core.api.service_client_structured_api_adapter_inventory_types import (
    AdapterEntry,
    read_entry,
)


CLAIMS_ADAPTERS = [
    AdapterEntry(
        function_id="claims.work.acquire",
        cli_invocation=(
            "yoke claims work acquire (--item PREFIX-N | --epic PREFIX-N --task-num N | --process KEY) [--project P] [--reason TEXT] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="claims.work.release",
        cli_invocation=(
            "yoke claims work release (--claim-id N | --item PREFIX-N | --epic PREFIX-N --task-num N | --process KEY | --all-mine) [--project P] [--reason TEXT] [--session-id S] [--json]\nPick exactly one claim to release. Every choice except --all-mine\nneeds --reason.\nReleasing a QA_HOST:<machine> claim by --claim-id hands the host to\nthe session that has waited longest for it and wakes that session."
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
            "yoke claims path amend --claim-id N (--add-paths PATH1,PATH2,... | --remove-paths PATH1,PATH2,...) --reason TEXT --item PREFIX-N [--integration-target BRANCH] [--allow-planned] [--directory-paths PATH1,PATH2,...] [(--db-claim-json JSON | --db-claim-file PATH)] [--project P] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "claims.path.release",
        (
            "yoke claims path release --item PREFIX-N --claim-id N --reason TEXT [--project P] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "claims.path.cancel",
        (
            "yoke claims path cancel --item PREFIX-N --claim-id N --reason TEXT [--project P] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        function_id="claims.path.override",
        cli_invocation=(
            "yoke claims path override --claim-id N --override-point creation|amend|revalidation_conflict --integration-target TARGET --actor-id N --actor-reason TEXT [--blocking-claim-id M] [--blocking-path-targets ID,ID,...] [--conflict-reason REASON] [--item PREFIX-N] [--project SLUG] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "claims.path.activation_run",
        "python3 -m yoke_core.cli.db_router path-claims activation-run",
    ),
    AdapterEntry(
        "claims.path.coordination_decision_build",
        (
            "yoke claims path coordination-decision-build (--item | --candidate-item) PREFIX-N --conflicting-claim CLAIM_ID --paths PATH1,PATH2,... [--project P] [--full] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "claims.path.boundary_prove",
        (
            "yoke claims path boundary-prove --item PREFIX-N [--project P] [--session-id S] [--json]"
        ),
    ),
    AdapterEntry(
        "claims.coordination_claim.acquire",
        "python3 -m yoke_core.api.service_client coordination-claim-acquire",
    ),
    AdapterEntry(
        "claims.coordination_claim.acquire_if_free",
        "python3 -m yoke_core.domain.test_machine_power (cloud host stop hold)",
    ),
    AdapterEntry(
        "claims.coordination_claim.heartbeat",
        "python3 -m yoke_core.api.service_client coordination-claim-heartbeat",
    ),
    AdapterEntry(
        "claims.coordination_claim.release",
        (
            "yoke claims coordination-claim release (--project P --key K | --claim-id N) --reason TEXT [--json]"
        ),
    ),
    AdapterEntry(
        "claims.coordination_claim.operator_release",
        (
            "yoke coordination-claim release [--project P] --key K --claim-id N --holder-session-id S --reason R [--json]"
        ),
        agent_path="operator-only",
    ),
    AdapterEntry(
        "claims.coordination_claim.list",
        "python3 -m yoke_core.api.service_client coordination-claim-list",
    ),
    AdapterEntry(
        "claims.steering.acquire",
        (
            "yoke claims steering acquire --project P [--doc SLUG | --plan-doc SLUG] [--reason TEXT] [--json]"
        ),
    ),
    AdapterEntry(
        "claims.steering.release",
        ("yoke claims steering release CLAIM_ID --reason TEXT [--json]"),
    ),
    read_entry(
        function_id="claims.steering.list",
        cli_invocation=(
            "yoke claims steering list [--project P] [--session-id S] [--active-only] [--full] [--json]"
        ),
    ),
    read_entry(
        function_id="claims.steering.verify",
        cli_invocation=("yoke claims steering verify --project P [--full] [--json]"),
    ),
    AdapterEntry(
        "steering.report.get",
        ("yoke steering report get [--project P] [--full] [--json]"),
    ),
]


__all__ = ["CLAIMS_ADAPTERS"]
