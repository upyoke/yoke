"""Built-in QA method definitions and reusable runner metadata."""

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
        "concurrency_mode": "parallel",
        "runner_id": "worktree_run",
        "required_capability_kinds": [],
        "verdict_path": "automatic",
        "verdict_contract": "exit 0 = pass",
        "evidence_contract": "exit code · captured output tail",
        "display_icon": "⌥",
        "display_order": 10,
        "display_group": "Command",
        "config_contract_id": "command",
        "proof_kind": "command",
        "runner_gloss": "runs the case's command in the item worktree",
    },
    {
        "id": "command-ci",
        "name": "Command (CI)",
        "description": (
            "Run the project's deterministic commands on its CI workflow — "
            "the run's conclusion is the verdict, its URL and head sha are "
            "the evidence."
        ),
        "concurrency_mode": "parallel",
        "runner_id": "ci_run",
        "required_capability_kinds": [],
        "verdict_path": "automatic",
        "verdict_contract": "workflow run concluded success = pass",
        "evidence_contract": "run url · head sha · run conclusion",
        "display_icon": "⌥",
        "display_order": 20,
        "display_group": "Command",
        "config_contract_id": "command-ci",
        "proof_kind": "command",
        "runner_gloss": "runs the project-declared equivalent in CI",
    },
    {
        "id": "browser-check",
        "name": "Browser check",
        "description": (
            "Playwright-style assertions against declared routes; automatic verdict."
        ),
        "concurrency_mode": "parallel",
        "runner_id": "browser_substrate",
        "required_capability_kinds": ["browser-control"],
        "verdict_path": "automatic",
        "verdict_contract": "assertions",
        "evidence_contract": "assertions · trace · logs",
        "display_icon": "◎",
        "display_order": 30,
        "display_group": "Browser",
        "config_contract_id": "browser-check",
        "proof_kind": "browser-check",
        "runner_gloss": "the registered browser-control substrate",
    },
    {
        "id": "browser-inspection",
        "name": "Browser inspection",
        "description": (
            "Captures screenshots; an agent judges whether they show the "
            "case's expected outcome."
        ),
        "concurrency_mode": "parallel",
        "runner_id": "browser_substrate",
        "required_capability_kinds": ["browser-control"],
        "verdict_path": "agent",
        "verdict_contract": (
            "agent verdict is pass, fail, or undetermined; undetermined "
            "requires attached evidence, halts the item for owner/operator "
            "review, and names what could not be established and why"
        ),
        "evidence_contract": "screenshots · inspection verdict",
        "display_icon": "◉",
        "display_order": 40,
        "display_group": "Browser",
        "config_contract_id": "browser-inspection",
        "proof_kind": "browser-inspection",
        "runner_gloss": "the registered browser-control substrate",
    },
    {
        "id": "terminal-check",
        "name": "Terminal check",
        "description": "Scripted PTY interaction with any terminal program; "
        "transcript + checkpoint expectations.",
        "runner_id": "host_control",
        "required_capability_kinds": ["test-machine"],
        "verdict_path": "automatic",
        "verdict_contract": "transcript checkpoints met",
        "evidence_contract": "step transcript · checkpoint expectations",
        "concurrency_mode": "serial",
        "display_icon": "⌨",
        "display_order": 50,
        "display_group": "Machine",
        "config_contract_id": "terminal-check",
        "proof_kind": "terminal-check",
        "runner_gloss": "SSH + PTY on the capability-named machine",
    },
    {
        "id": "terminal-inspection",
        "name": "Terminal inspection",
        "description": "Real Terminal screenshots at checkpoints; an agent judges "
        "them against the expected outcome.",
        "runner_id": "host_control",
        "required_capability_kinds": ["test-machine"],
        "verdict_path": "agent",
        "verdict_contract": "agent verdict is pass, fail, or undetermined; "
        "undetermined requires a reason naming what could not "
        "be established and why",
        "evidence_contract": "paired text + Terminal screenshots · inspection "
        "verdict — blocked image capture reports the text plus "
        "the reason as a degraded outcome, never a silent pass",
        "concurrency_mode": "serial",
        "display_icon": "⌘",
        "display_order": 60,
        "display_group": "Machine",
        "config_contract_id": "terminal-inspection",
        "proof_kind": "terminal-inspection",
        "runner_gloss": "SSH + PTY on the capability-named machine",
    },
    {
        "id": "machine-state-check",
        "name": "Machine state check",
        "description": "Shell assertions on the controlled host, including declared "
        "macOS GUI-session commands.",
        "runner_id": "host_control",
        "required_capability_kinds": ["test-machine"],
        "verdict_path": "automatic",
        "verdict_contract": "expected exit on the host with every required session "
        "context available",
        "evidence_contract": "assertion commands · outputs · execution context or "
        "degraded reason · secret scan",
        "concurrency_mode": "serial",
        "display_icon": "≡",
        "display_order": 70,
        "display_group": "Machine",
        "config_contract_id": "machine-state-check",
        "proof_kind": "machine-state-check",
        "runner_gloss": "SSH or declared macOS GUI-session assertions on the "
        "controlled host",
    },
    {
        "id": "exploratory-mission",
        "name": "Exploratory mission",
        "description": "Agent-chosen exploration across declared substrates; an "
        "missions without a declared host explore on the controller. Do not use it for "
        "deterministic checks: Command methods are faster, cheaper, "
        "and repeatable.",
        "runner_id": "agent_mission",
        "required_capability_kinds": ["browser-control"],
        "verdict_path": "agent",
        "verdict_contract": "the mission owner submits pass, fail, or undetermined "
        "with a written rationale; undetermined names what "
        "could not be established and why",
        "evidence_contract": "ranked written findings are primary; deliberate proof "
        "artifacts stay within the runtime-supplied limit, "
        "while routine perception is discarded",
        "concurrency_mode": "serial",
        "display_icon": "⌁",
        "display_order": 80,
        "display_group": "Machine",
        "config_contract_id": "agent-mission",
        "proof_kind": "exploratory-mission",
        "runner_gloss": "Main-owned mission with an informed subagent walker",
    },
)


def method_metadata_for_runner(
    runner_id: str,
    verdict_path: str,
) -> dict[str, Any]:
    """Return reusable method metadata for one registered runner contract."""
    for method in BUILTIN_QA_METHODS:
        if method["runner_id"] == runner_id and method["verdict_path"] == verdict_path:
            return {
                key: method[key]
                for key in (
                    "display_icon",
                    "display_order",
                    "display_group",
                    "config_contract_id",
                    "proof_kind",
                    "runner_gloss",
                )
            }
    return {
        "display_icon": "◉",
        "display_order": 1000,
        "display_group": "Project",
        "config_contract_id": "passthrough",
        "proof_kind": "artifact",
        "runner_gloss": "registered runner",
    }


def method_read_metadata(row: Any) -> dict[str, Any]:
    """Project definition-owned metadata from a stored method row."""
    return {
        "display_icon": str(row["display_icon"]),
        "display_order": int(row["display_order"]),
        "display_group": str(row["display_group"]),
        "config_contract_id": str(row["config_contract_id"]),
        "proof_kind": str(row["proof_kind"]),
        "runner_gloss": str(row["runner_gloss"]),
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
    "method_metadata_for_runner",
    "method_presentations",
    "method_read_metadata",
]
