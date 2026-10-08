"""Stable semantic fields included in frozen release QA snapshots."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any


PLAN_FIELDS = (
    "id",
    "project_id",
    "slug",
    "name",
    "description",
    "success_policy_id",
    "success_policy_params",
    "target_environment_id",
)
CASE_FIELDS = (
    "id",
    "plan_id",
    "case_key",
    "position",
    "method_id",
    "instructions",
    "expected_outcome",
    "method_config",
    "success_policy_id",
    "success_policy_params",
    "host_baselines",
    "starting_state",
    "starting_state_reason",
    "entry_surface",
    "required_completion",
    "method_name",
    "runner_id",
    "required_capability_kinds",
    "verdict_path",
    "config_contract_id",
)
REQUIREMENT_FIELDS = (
    "id",
    "item_id",
    "deployment_run_id",
    "qa_kind",
    "qa_phase",
    "target_env",
    "blocking_mode",
    "requirement_source",
    "success_policy",
    "capability_requirements",
    "suite_id",
    "plan_id",
    "plan_case_key",
    "case_position",
    "baseline_position",
    "method_id",
    "method_name",
    "runner_id",
    "verdict_path",
    "host_baseline",
    "starting_state",
    "starting_state_reason",
    "entry_surface",
    "required_completion",
    "workflow_transition_id",
    "instructions",
    "expected_outcome",
    "method_config",
    "execution_target_json",
)
JSON_FIELDS = frozenset(
    {
        "success_policy_params",
        "method_config",
        "host_baselines",
        "required_capability_kinds",
        "success_policy",
        "capability_requirements",
        "execution_target_json",
    }
)


PLAN_CASE_COLUMNS = (
    "id",
    "plan_id",
    "case_key",
    "position",
    "method_id",
    "instructions",
    "expected_outcome",
    "method_config",
    "success_policy_id",
    "success_policy_params",
    "host_baselines",
    "starting_state",
    "starting_state_reason",
    "entry_surface",
    "required_completion",
)


def converged_select(
    conn: Any, table: str, fields: Iterable[str], alias: str = ""
) -> str:
    """Select each field, or NULL for a column this database has not gained yet.

    A deployment run freezes its members in-process against the authoritative
    database before the release that adds a column boots and converges it, so
    a freeze that named a new column outright would refuse every run started
    from that source — the converging release included.
    """
    from yoke_core.domain.schema_common import _get_columns

    present = set(_get_columns(conn, table))
    prefix = f"{alias}." if alias else ""
    return ",".join(
        f"{prefix}{field}" if field in present else f"NULL AS {field}"
        for field in fields
    )


def semantic_row(row: Mapping[str, Any], fields: Iterable[str]) -> dict[str, Any]:
    """Return only configured acceptance fields with decoded JSON values."""
    result = {field: row.get(field) for field in fields}
    for field in JSON_FIELDS & result.keys():
        value = result[field]
        if value not in (None, "") and not isinstance(value, (dict, list)):
            result[field] = json.loads(str(value))
    return result
