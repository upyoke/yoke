"""Built-in QA method definitions and reusable executor metadata."""

from __future__ import annotations

from typing import Any


BUILTIN_QA_METHODS = (
    {
        "id": "command",
        "name": "Command",
        "description": (
            "Run the project's deterministic commands in a worktree — "
            "exit 0 is the verdict, captured output is the evidence."
        ),
        "executor_id": "worktree_run",
        "required_capability_kind": None,
        "verdict_path": "automatic",
        "verdict_contract": "exit 0 = pass",
        "evidence_contract": "exit code · captured output tail",
        "display_icon": "⌥",
        "display_order": 10,
        "display_group": "Command",
        "config_contract_id": "command",
        "proof_kind": "command",
        "executor_gloss": "runs the case's command in the item worktree",
    },
    {
        "id": "command-ci",
        "name": "Command (CI)",
        "description": (
            "Run the project's deterministic commands on its CI workflow — "
            "the run's conclusion is the verdict, its URL and head sha are "
            "the evidence."
        ),
        "executor_id": "ci_run",
        "required_capability_kind": None,
        "verdict_path": "automatic",
        "verdict_contract": "workflow run concluded success = pass",
        "evidence_contract": "run url · head sha · run conclusion",
        "display_icon": "⌥",
        "display_order": 20,
        "display_group": "Command",
        "config_contract_id": "command",
        "proof_kind": "command",
        "executor_gloss": "runs the project-declared equivalent in CI",
    },
    {
        "id": "browser-check",
        "name": "Browser check",
        "description": (
            "Playwright-style assertions against declared routes; automatic verdict."
        ),
        "executor_id": "browser_substrate",
        "required_capability_kind": "browser-control",
        "verdict_path": "automatic",
        "verdict_contract": "assertions",
        "evidence_contract": "assertions · trace · logs",
        "display_icon": "◎",
        "display_order": 30,
        "display_group": "Browser",
        "config_contract_id": "browser-check",
        "proof_kind": "browser-check",
        "executor_gloss": "the registered browser-control substrate",
    },
    {
        "id": "browser-inspection",
        "name": "Browser inspection",
        "description": (
            "Captures screenshots; an agent judges whether they show the "
            "case's expected outcome."
        ),
        "executor_id": "browser_substrate",
        "required_capability_kind": "browser-control",
        "verdict_path": "agent",
        "verdict_contract": (
            "inspects the screenshot and judges whether it shows the case's "
            "expected outcome"
        ),
        "evidence_contract": "screenshots · inspection verdict",
        "display_icon": "◉",
        "display_order": 40,
        "display_group": "Browser",
        "config_contract_id": "browser-inspection",
        "proof_kind": "browser-inspection",
        "executor_gloss": "the registered browser-control substrate",
    },
)


def method_metadata_for_executor(
    executor_id: str,
    verdict_path: str,
) -> dict[str, Any]:
    """Return reusable method metadata for one registered executor contract."""
    for method in BUILTIN_QA_METHODS:
        if (
            method["executor_id"] == executor_id
            and method["verdict_path"] == verdict_path
        ):
            return {
                key: method[key]
                for key in (
                    "display_icon",
                    "display_order",
                    "display_group",
                    "config_contract_id",
                    "proof_kind",
                    "executor_gloss",
                )
            }
    return {
        "display_icon": "◉",
        "display_order": 1000,
        "display_group": "Project",
        "config_contract_id": "passthrough",
        "proof_kind": "artifact",
        "executor_gloss": "registered executor",
    }


def method_read_metadata(row: Any) -> dict[str, Any]:
    """Project definition-owned metadata from a stored method row."""
    return {
        "display_icon": str(row["display_icon"]),
        "display_order": int(row["display_order"]),
        "display_group": str(row["display_group"]),
        "config_contract_id": str(row["config_contract_id"]),
        "proof_kind": str(row["proof_kind"]),
        "executor_gloss": str(row["executor_gloss"]),
    }


def method_presentations(rows: list[Any]) -> list[dict[str, Any]]:
    """Deduplicate compact display metadata for plan summaries."""
    return list(
        {
            str(row["method_id"]): {
                "id": str(row["method_id"]),
                "icon": str(row["display_icon"]),
                "order": int(row["display_order"]),
                "group": str(row["display_group"]),
            }
            for row in rows
        }.values()
    )


__all__ = [
    "BUILTIN_QA_METHODS",
    "method_metadata_for_executor",
    "method_presentations",
    "method_read_metadata",
]
