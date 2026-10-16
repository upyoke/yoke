"""Exercise public control-plane routes without adding production learning data."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from urllib.parse import urlsplit

from yoke_cli.config.machine_config import active_connection
from yoke_contracts.machine_config.schema import MachineConfigContractError


def _https_origin(value: str) -> tuple[str, int] | None:
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            return None
        port = parsed.port
        return parsed.hostname, 443 if port is None else port
    except ValueError:
        return None


def require_target() -> None:
    base_url = os.environ.get("BASE_URL", "").strip().rstrip("/")
    try:
        connection = active_connection()
    except MachineConfigContractError as exc:
        raise RuntimeError(
            "agent_route_connection_unavailable: restore the authenticated HTTPS "
            "connection for BASE_URL, then rerun this member case"
        ) from exc
    expected_origin = _https_origin(base_url)
    if (
        expected_origin is None
        or connection.get("transport") != "https"
        or _https_origin(str(connection.get("api_url") or "")) != expected_origin
    ):
        raise RuntimeError(
            "agent_route_target_mismatch: select the authenticated HTTPS connection "
            "for the runner's BASE_URL origin, keeping its organization API path, "
            "then rerun this member case"
        )


def call(*args: str, stdin: str | None = None) -> dict:
    completed = subprocess.run(
        ["yoke", *args, "--json"],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if completed.stderr:
        print(completed.stderr, file=sys.stderr, end="")
    try:
        response = json.loads(completed.stdout)
    except ValueError as exc:
        raise RuntimeError(
            f"agent_route_response_invalid: {' '.join(args)}; inspect CLI output "
            "and repair the public adapter before rerunning this probe"
        ) from exc
    if not response.get("success"):
        raise RuntimeError(
            f"agent_route_refused: {response.get('error')}; follow the named recovery "
            "and rerun against the same delivered candidate"
        )
    return response["result"]


def main() -> int:
    member = os.environ.get("DEPLOYMENT_MEMBER_REF", "").strip()
    project = os.environ.get("YOKE_PROJECT", "").strip()
    if not member or not project:
        print(
            "agent_route_subject_missing: run this probe through the member's post-deploy Command case",
            file=sys.stderr,
        )
        return 2
    try:
        require_target()
        gate = call(
            "advance", "preflight", "hard-blocks", member, "--gate-point", "activation"
        )
        if not isinstance(gate["blockers"], list):
            raise RuntimeError(
                "agent_route_gate_shape: blockers must be a list; repair the served response"
            )
        capture = call(
            "ouroboros",
            "reflection",
            "capture",
            "--stdin",
            "--project",
            project,
            "--default-agent",
            "engineer",
            stdin="---REFLECTION-START---\n---REFLECTION-END---\n",
        )
        for field in (
            "entries_parsed",
            "entries_persisted",
            "entries_persist_failed",
            "entries_duplicate_skipped",
        ):
            if capture[field] != 0:
                raise RuntimeError(
                    f"agent_route_empty_capture: {field} was nonzero; inspect parser and rerun"
                )
        if capture["errors"] or capture["blocks_seen"] != 1:
            raise RuntimeError(
                "agent_route_capture_diagnostics: empty envelope was not recognized; repair parser"
            )
        audit = subprocess.run(
            ["yoke", "merge", "audit", member, "--project", project],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if audit.returncode or "# Merge Readiness Audit" not in audit.stdout:
            raise RuntimeError(
                f"agent_route_audit_failed: {audit.stderr}; follow snapshot recovery and rerun"
            )
    except KeyError as exc:
        print(
            f"agent_route_response_missing: {exc}; ask the control-plane operator to verify the carrying release, then rerun",
            file=sys.stderr,
        )
        return 1
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(
            f"agent_route_command_unavailable: {exc}; restore the public CLI and connection, then rerun",
            file=sys.stderr,
        )
        return 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        "public agent routes passed: dependency gate, empty reflection receipt, local merge audit; no learning rows created"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
