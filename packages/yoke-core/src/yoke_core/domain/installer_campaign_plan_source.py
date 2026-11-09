"""Source-authored installer cases and comparison against a saved plan."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from yoke_contracts.qa_case_starting_state import BASELINE
from yoke_core.domain.installer_campaign_execution_target import installer_campaign_cases_for_target

_CASE_DEFAULTS: dict[str, Any] = {
    "case_key": None,
    "position": None,
    "method_id": None,
    "instructions": None,
    "expected_outcome": None,
    "method_config": {},
    "success_policy_id": None,
    "success_policy_params": None,
    "host_baselines": [],
    "starting_state": None,
    "starting_state_reason": None,
    "entry_surface": None,
    "required_completion": None,
}



SOURCE_AUTHORED_PLAN_SLUGS = ("installer-campaign", "installer-exploration")



def _authored(case: dict[str, Any], field: str) -> Any:
    """One authored field, with a stored baseline case's normalized state.

    Authoring stores a case that names ``host_baselines`` as
    ``starting_state: "baseline"``; the source leaves it implied.
    """
    value = case.get(field, _CASE_DEFAULTS[field])
    if field == "starting_state" and value is None and case.get("host_baselines"):
        return BASELINE
    return value



def _source_cases(
    plan: dict[str, Any], primary_machine=None, joining_machine=None
) -> list[dict]:
    slug = plan["slug"]
    if slug == "installer-campaign":
        configured = {case["case_key"]: case for case in plan["cases"]}
        primary_machine = primary_machine or configured.get("path-on-shell", {}).get(
            "method_config", {}
        ).get("test_machine")
        joining_machine = joining_machine or configured.get(
            "second-machine-join", {}
        ).get("method_config", {}).get("test_machine")
        return installer_campaign_cases_for_target(
            plan["execution_target"],
            primary_machine=primary_machine,
            joining_machine=joining_machine,
        )
    if slug == "installer-exploration":
        return json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "domain"
                / "installer_exploration_cases.json"
            ).read_text()
        )
    raise ValueError(
        f"unsupported installer plan {slug!r}; read installer-campaign or "
        "installer-exploration with yoke qa plan get before exporting."
    )



def compare_plan(
    plan: dict[str, Any], *, primary_machine=None, joining_machine=None
) -> tuple[list[dict], dict]:
    """Compare authored fields, excluding row identity and historical proof."""
    cases = _source_cases(plan, primary_machine, joining_machine)
    installed = {case["case_key"]: case for case in plan["cases"]}
    generated = {case["case_key"]: case for case in cases}
    if len(installed) != len(plan["cases"]):
        raise ValueError("installed plan contains duplicate case keys")
    differences = []
    for key in sorted(installed.keys() | generated.keys()):
        if key not in installed or key not in generated:
            differences.append(
                {
                    "case_key": key,
                    "change": "added" if key in generated else "removed",
                }
            )
            continue
        fields = [
            field
            for field in _CASE_DEFAULTS
            if _authored(installed[key], field) != _authored(generated[key], field)
        ]
        if fields:
            differences.append({"case_key": key, "fields": fields})
    return cases, {
        "plan_id": plan["id"],
        "target_environment": plan["target_environment"],
        "case_count": len(cases),
        "matches_source": not differences,
        "differences": differences,
    }

