"""Compact, permission-scoped setup context for hooks and command replies."""

from pathlib import Path
from typing import Any, Mapping

from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.onboard_checklist import (
    SCHEMA_VERSION,
    FIRST_ITEM_DONE_ROW_ID,
    REQUIRED_SETUP_ROW_IDS,
    STATUS_CONFIGURED,
    STATUS_VERIFIED,
)

MACHINE_HOME = "https://upyoke.com/docs/start/agent-setup"


def summary_lines(report: Mapping[str, Any], *, orientation: bool = False) -> list[str]:
    run = report.get("run", report)
    if not isinstance(run, Mapping):
        return [
            "Setup: no saved run; run yoke onboard checklist init --project P --checkout PATH"
        ]
    rows = run.get("rows") or []
    if (
        orientation
        and (run.get("setup_readiness") or {}).get("ready")
        and not any(row["status"] in ("blocked", "needed") for row in rows)
        and any(
            row["row_id"] == FIRST_ITEM_DONE_ROW_ID
            and row["status"] in (STATUS_CONFIGURED, STATUS_VERIFIED)
            for row in rows
        )
    ):
        return []
    counts = sum(row["status"] in (STATUS_CONFIGURED, STATUS_VERIFIED) for row in rows)
    parts = [f"{counts} configured/verified"]
    for status in ("deferred", "not-needed", "unknown", "blocked", "needed"):
        names = [
            row["row_id"]
            for row in rows
            if row["status"] == status
            and (
                not orientation
                or status in ("deferred", "not-needed", "blocked", "needed")
                or row["row_id"] in REQUIRED_SETUP_ROW_IDS
                or row["row_id"] == FIRST_ITEM_DONE_ROW_ID
            )
        ]
        if names:
            parts.append(status + " " + ", ".join(names))
    lines = ["Setup: " + " · ".join(parts)]
    action = run.get("next_action")
    if action:
        lines.append(next_line(action))
    return lines


def next_line(action: Mapping[str, Any]) -> str:
    return f"Next: {action['command']} ({action['reason']}) — more: {action['home']}"


def read_project(
    root: str | Path,
    *,
    project: str | int | None = None,
    config_path: str | Path | None = None,
    orientation: bool = False,
) -> dict[str, Any]:
    from yoke_cli.commands._helpers import ensure_handlers_loaded
    from yoke_cli.config import machine_config, onboard_setup_facts
    from yoke_cli.transport.dispatcher import call_dispatcher

    from yoke_cli.config.project_onboard_support import machine_config_path

    try:
        with machine_config_path(config_path):
            facts = onboard_setup_facts.collect(
                config_path=config_path, checkout_path=root
            )
            selected = project or machine_config.project_id(Path(root), config_path)
            if selected is None:
                return _failure(
                    "setup_project_unbound",
                    "Run yoke project register PATH --project-id N.",
                )
            ensure_handlers_loaded()
            response = call_dispatcher(
                function_id="onboard.checklist.get",
                target=TargetRef(kind="global", project_id=str(selected)),
                payload={"project": str(selected), **facts},
            )
            if not response.success:
                error = response.error
                if error and error.code == "permission_denied":
                    return {"lines": [], "next_action": None}
                return _failure(
                    error.code if error else "setup_facts_unavailable",
                    (
                        error.recovery_hint
                        or (
                            error.message
                            + " Run yoke onboard checklist get to diagnose and retry."
                        )
                    )
                    if error
                    else "Run yoke onboard checklist get to diagnose the read.",
                )
            report = response.result or {}
            if report.get("schema_version") != SCHEMA_VERSION:
                return _failure(
                    "setup_facts_unavailable",
                    "Ask the control-plane operator to serve checklist schema 2.",
                )
            run = report.get("run")
            return {
                "lines": summary_lines(report, orientation=orientation),
                "next_action": run.get("next_action")
                if isinstance(run, dict)
                else None,
            }
    except Exception as exc:  # hooks and completed setup writes must still return
        code, separator, recovery = str(exc).partition(":")
        if not code.replace("_", "").isalnum() or "_" not in code:
            code = "setup_facts_unavailable"
            recovery = ""
        return _failure(
            code,
            recovery.strip()
            if separator and recovery.strip()
            else "Run yoke onboard checklist get to diagnose and retry.",
        )


def machine_summary() -> dict[str, Any]:
    from yoke_cli.config.onboard_setup_facts import collect

    try:
        observations = collect(machine_only=True)["observations"]
        missing = [
            key
            for key in ("package-install", "machine-profile", "yoke-connection")
            if observations.get(key, {}).get("status") != STATUS_CONFIGURED
        ]
        action = {
            "row_id": missing[0] if missing else "project-folder",
            "title": "Machine setup" if missing else "Project folder",
            "status": "unknown" if missing else "needed",
            "reason": "machine_prerequisite_missing" if missing else "outside_project",
            "command": "yoke setup --agent"
            if missing
            else "Use yoke-global, then open a session in the project folder.",
            "home": MACHINE_HOME,
        }
        rows = [{"row_id": key, **value} for key, value in observations.items()]
        return {
            "lines": summary_lines({"rows": rows, "next_action": action}),
            "next_action": action,
        }
    except Exception:
        return _failure(
            "setup_machine_config_unreadable", "Run yoke setup --agent on this machine."
        )


def orientation_lines(root: Path | None) -> list[str]:
    return (
        machine_summary() if root is None else read_project(root, orientation=True)
    )["lines"]


def _failure(code: str, recovery: str) -> dict[str, Any]:
    return {
        "lines": [f"Setup: {code}; {' '.join(recovery.split())}"],
        "next_action": None,
    }
