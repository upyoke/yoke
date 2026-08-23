"""Top-level-only deployed acceptance runner for Fleet session control."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Sequence

from runtime.api.tools.session_control_live_acceptance_client import YokeCliClient
from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceContractError,
    load_candidate_matrix,
    load_matrix,
    validate_deployed_release,
    validate_run_id,
)
from runtime.api.tools.session_control_live_acceptance_driver import (
    LiveAcceptanceDriver,
)
from runtime.api.tools.session_control_live_acceptance_qualification import (
    QualificationCoordinator,
)
from yoke_contracts.session_control.private_route_qualification import (
    QUALIFICATION_TTL_SECONDS,
)
from yoke_cli.config import machine_config
from yoke_contracts.machine_config.schema import connection_is_prod
from yoke_contracts.session_identity import (
    ANCHORS_DIR_NAME,
    CURSOR_SESSION_MAP_DIR_NAME,
    resolve_ambient_session_id,
)


def _is_subagent_execution() -> bool:
    """Use the shared fact when present; keep this older worker lane closed."""
    try:
        from yoke_contracts.session_execution import is_subagent_execution

        return is_subagent_execution()
    except ImportError:
        if str(os.environ.get("YOKE_HOOK_AGENT_TYPE") or "").strip():
            return True
        parent = str(os.environ.get("CODEX_SESSION_ID") or "").strip()
        thread = str(os.environ.get("CODEX_THREAD_ID") or "").strip()
        if parent and thread and parent != thread:
            return True
        transcript = str(os.environ.get("CURSOR_TRANSCRIPT_PATH") or "")
        return "subagents" in Path(transcript.replace("\\", "/")).parts


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run version-pinned Fleet create/delivery/ack/wait/wake acceptance. "
            "This mutates live session-control state and must run in a top-level session."
        )
    )
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument(
        "--qualification-candidate",
        action="store_true",
        help=(
            "Run a stage-only subset of unproven private-route candidates. "
            "Without this flag the full pinned acceptance matrix is required."
        ),
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--release-sha",
        required=True,
        help="Full 40-character commit expected in the deployed environment.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--unsupported-observation-seconds", type=float, default=90.0)
    return parser


def _caller_session_id() -> str:
    try:
        home = machine_config.yoke_home()
        value = resolve_ambient_session_id(
            home / ANCHORS_DIR_NAME,
            os.environ,
            cursor_map_dir=home / CURSOR_SESSION_MAP_DIR_NAME,
        )
    except Exception as exc:  # an unbound caller must fail closed
        raise AcceptanceContractError("caller_identity_unresolved") from exc
    if not isinstance(value, str) or not value.strip():
        raise AcceptanceContractError("caller_identity_unresolved")
    return value.strip()


def _require_stage_qualification_environment() -> None:
    try:
        environment = str(machine_config.active_env() or "").strip()
        connection = machine_config.active_connection()
    except Exception as exc:
        raise AcceptanceContractError("qualification_environment_unresolved") from exc
    if environment != "stage" or connection_is_prod(connection):
        raise AcceptanceContractError("qualification_stage_required")


def _refusal(exc: AcceptanceContractError) -> dict[str, object]:
    report: dict[str, object] = {
        "schema": 1,
        "kind": "fleet_session_control_live_acceptance",
        "status": "refused",
        "failure_code": exc.code,
    }
    if exc.surface:
        report["surface"] = exc.surface
    return report


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if _is_subagent_execution():
            raise AcceptanceContractError("top_level_session_required")
        run_id = validate_run_id(args.run_id)
        if args.timeout_seconds <= 0 or args.poll_seconds <= 0:
            raise AcceptanceContractError("poll_window_invalid")
        if args.unsupported_observation_seconds < 0:
            raise AcceptanceContractError("observation_window_invalid")
        if (
            args.qualification_candidate
            and args.timeout_seconds > QUALIFICATION_TTL_SECONDS / 2
        ):
            raise AcceptanceContractError("qualification_window_invalid")
        caller = _caller_session_id()
        if args.qualification_candidate:
            _require_stage_qualification_environment()
            matrix = load_candidate_matrix(args.matrix)
        else:
            matrix = load_matrix(args.matrix)
        client = YokeCliClient()
        release = client.deployed_release()
        release_sha, server_build = validate_deployed_release(
            args.release_sha, release.get("server_build", "")
        )
        qualification = (
            QualificationCoordinator(
                client,
                matrix,
                run_id=run_id,
                release_sha=release_sha,
                caller_session_id=caller,
            )
            if args.qualification_candidate
            else None
        )
        report = LiveAcceptanceDriver(client).run(
            matrix,
            run_id=run_id,
            release_sha=release_sha,
            server_build=server_build,
            engine_version=release.get("engine_version", ""),
            caller_session_id=caller,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
            unsupported_observation_seconds=args.unsupported_observation_seconds,
            qualification=qualification,
        )
        if qualification is not None:
            report["qualification_grants"] = qualification.evidence()
            report["qualification_grants_consumed"] = qualification.all_consumed
            if not qualification.all_consumed:
                report["status"] = "failed"
                report["failure_code"] = "qualification_not_consumed"
        code = 0 if report["status"] == "passed" else 1
    except AcceptanceContractError as exc:
        report = _refusal(exc)
        code = 2
    except Exception:
        report = _refusal(AcceptanceContractError("internal_error"))
        code = 2
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return code


if __name__ == "__main__":
    sys.exit(main())
