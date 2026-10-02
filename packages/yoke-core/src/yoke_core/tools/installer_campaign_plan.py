"""Export and compare installer cases using a registered plan's target snapshot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from yoke_core.domain.installer_campaign_execution_target import (
    installer_campaign_cases_for_target,
)


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
    "entry_surface": None,
    "required_completion": None,
}


def compare_plan(plan: dict[str, Any]) -> tuple[list[dict], dict]:
    """Compare authored fields, excluding row identity and historical proof."""
    cases = installer_campaign_cases_for_target(plan["execution_target"])
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
            for field, default in _CASE_DEFAULTS.items()
            if installed[key].get(field, default) != generated[key].get(field, default)
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--plan-file",
        type=Path,
        required=True,
        help="Full JSON receipt from yoke qa plan get.",
    )
    parser.add_argument(
        "--cases-file",
        type=Path,
        help="Export generated cases for qa.plan_cases.replace.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 when installed cases differ from source.",
    )
    args = parser.parse_args(argv)
    try:
        receipt = json.loads(args.plan_file.read_text())
        if receipt.get("success") is not True:
            raise ValueError("plan read did not succeed")
        cases, report = compare_plan(receipt["result"]["plan"])
        if args.cases_file:
            args.cases_file.write_text(json.dumps(cases, indent=2) + "\n")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(
            f"installer_campaign_plan_snapshot_invalid: {exc}; "
            "capture yoke qa plan get PLAN --project P --full --json "
            "again and verify its execution_target before retrying.",
            file=sys.stderr,
        )
        return 2
    print(json.dumps(report, indent=2))
    if args.check and not report["matches_source"]:
        print(
            "installer_campaign_plan_source_drift: installed cases differ; "
            "export with --cases-file, review the differences, then install "
            "with yoke qa plan-cases replace and check a fresh plan receipt.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
