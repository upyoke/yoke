"""Shared install and session selection and final agent setup readiness report."""

from __future__ import annotations

import contextlib
import importlib
import io
import json
from pathlib import Path


def connection_failure():
    """Read machine-local preflight through Doctor's classified engine seam."""
    return importlib.import_module(
        "yoke_core.engines.doctor_install"
    ).active_connection_failure()


def install_slugs() -> tuple[str, ...]:
    return importlib.import_module("yoke_core.engines.doctor_install").INSTALL_SLUGS


def session_slugs() -> tuple[str, ...]:
    return importlib.import_module("yoke_core.engines.doctor_session").SESSION_SLUGS


def setup_readiness(report: dict, kwargs: dict) -> dict:
    try:
        return _setup_readiness(report, kwargs)
    except Exception as exc:
        return {
            "ready": False,
            "results": [],
            "error": {
                "code": "INSTALL_DOCTOR_UNAVAILABLE",
                "cause": type(exc).__name__,
            },
            "recovery": "Repair the installed Yoke CLI and rerun `yoke doctor run --install --project P`.",
        }


def _setup_readiness(report: dict, kwargs: dict) -> dict:
    project = str(kwargs.get("project_slug") or "")
    if not project:
        project_report = report.get("project_onboarding") or {}
        project = str((project_report.get("project") or {}).get("id") or "")
    if not project:
        from yoke_cli.commands.adapters.doctor_machine_scope import machine_scope_rows

        rows = machine_scope_rows(
            install_slugs(), quick=False, fix=False, only=",".join(install_slugs())
        )
        compose = importlib.import_module("yoke_core.engines.doctor_https_compose")
        result = {"results": rows, **compose.recount(rows)}
    else:
        from yoke_cli.commands.adapters.doctor import doctor_run

        output, progress = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(progress):
            code = doctor_run(["--install", "--project", project, "--json"])
        try:
            response = json.loads(output.getvalue())
            result = dict(response.get("result") or {})
            if not response.get("success"):
                result["error"] = response.get("error") or {
                    "code": "INSTALL_DOCTOR_UNAVAILABLE"
                }
        except ValueError:
            result = {"error": {"code": "INSTALL_DOCTOR_UNAVAILABLE"}, "results": []}
        result["exit_code"] = code
    expected = set(install_slugs())
    rows = result.get("results") or []
    checkout = kwargs.get("project_checkout")
    if checkout:
        from yoke_cli.config.setup_agent_answering import _inside

        if not _inside(Path.cwd(), Path(checkout).expanduser()):
            deferred = expected & set(session_slugs())
            expected -= deferred
            session_rows = [
                row for row in rows
                if str(row.get("hc") or "").removeprefix("HC-") in deferred
            ]
            rows = [row for row in rows if row not in session_rows]
            result["results"] = rows
            compose = importlib.import_module("yoke_core.engines.doctor_https_compose")
            result.update(compose.recount(rows))
            if result.get("exit_code") == 1 and any(
                row.get("severity") not in {"PASS", "N/A"} for row in session_rows
            ) and all(_install_row_ready(row) for row in rows):
                result["exit_code"] = 0
            result["pending"] = [{
                "detail": "new project session verification pending",
                "checks": sorted(deferred),
                "next_action": (
                    f"Open a new chat in {checkout} and run `yoke doctor run --session`."
                ),
            }]
    observed = {str(row.get("hc") or "").removeprefix("HC-") for row in rows}
    if expected - observed and not result.get("error"):
        result["error"] = {
            "code": "INSTALL_DOCTOR_INCOMPLETE",
            "missing_checks": sorted(expected - observed),
        }
    result["ready"] = (
        expected <= observed
        and bool(rows)
        and not result.get("error")
        and all(_install_row_ready(row) for row in rows)
        and result.get("exit_code", 0) == 0
    )
    result["recovery"] = (
        "Resolve each failed check's next step, then rerun `yoke doctor run --install --project P`."
    )
    return result


def _install_row_ready(row: dict) -> bool:
    return row.get("severity") in {"PASS", "N/A"} or (
        str(row.get("hc") or "").removeprefix("HC-") == "harness-cli-auth"
        and row.get("severity") == "WARN"
    )


def normalize_install_result(payload: dict, result: dict) -> None:
    """Older serving applicability cannot certify unknown configured GitHub auth."""
    if payload.get("only") != ",".join(install_slugs()):
        return
    changed = False
    for row in result.get("results", []):
        if str(row.get("hc") or "").removeprefix("HC-") != "project-gh-auth":
            continue
        severity = row.get("severity")
        detail = str(row.get("detail") or "")
        if severity in {"PASS", "FAIL"} or (
            severity == "N/A" and "disabled" in detail.lower()
        ):
            continue
        row.update(
            severity="FAIL",
            detail=(
                f"GITHUB_AUTH_UNVERIFIED: serving Doctor did not verify configured auth: {detail}. "
                "Required serving feature: install readiness for every project. Ask the control-plane operator to deploy the release carrying that feature, then retry."
            ),
        )
        changed = True
    if changed:
        compose = importlib.import_module("yoke_core.engines.doctor_https_compose")
        result.update(compose.recount(result["results"]))
