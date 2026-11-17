"""Hand a begun release-run QA execution to its candidate controller runtime.

The installed controller begins (or resumes) the execution, finds that it is
not the run's candidate build, and calls :func:`hand_off`. That runs this
module under the candidate runtime's interpreter with a private request file
holding the begun execution view, so the candidate adopts it without a second
begin or resume. The candidate then performs every case's controller work and
writes its plan result (or its named refusal) to the response file, which the
installed controller reports as its own. Python's ``-I`` keeps the installed
or source ``PYTHONPATH`` from leaking into the candidate.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from yoke_core.domain.qa_controller_candidate import (
    CONTROLLER_RUNTIME_ENV,
    CONTROLLER_RUNTIME_KEY,
    ControllerCandidate,
    controller_runtime_identity,
    not_candidate_refusal,
)
from yoke_core.domain.qa_plan_execution_result_state import QaPlanExecutionError
from yoke_core.tools.qa_controller_runtime import (
    HANDOFF_MODULE,
    ControllerRuntime,
    ControllerRuntimeError,
    ensure_controller_runtime,
)

Runner = Callable[..., subprocess.CompletedProcess]


def provision(candidate: ControllerCandidate) -> ControllerRuntime:
    """The candidate runtime, or the named pre-lease refusal."""
    try:
        return ensure_controller_runtime(
            base_url=candidate.installer_base_url,
            version=candidate.version,
            source_commit=candidate.source_commit,
        )
    except ControllerRuntimeError as exc:
        raise not_candidate_refusal(candidate, str(exc)) from exc


def hand_off(
    runtime: ControllerRuntime,
    *,
    execution: Mapping[str, Any],
    plan_kwargs: Mapping[str, Any],
    session_id: str,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Run the begun execution's controller work in *runtime*; return its result."""
    execution_id = str(execution.get("execution_id") or execution.get("id") or "")
    env = {**os.environ, CONTROLLER_RUNTIME_ENV: str(runtime.root)}
    if session_id:
        env["YOKE_SESSION_ID"] = session_id
    print(
        f"yoke qa plan run: controller work for execution {execution_id} runs on "
        f"candidate Yoke {runtime.version} ({runtime.source_commit[:12]}) from "
        f"{runtime.root}; the installed CLI is unchanged.",
        file=sys.stderr,
        flush=True,
    )
    with tempfile.TemporaryDirectory(prefix="yoke-qa-controller-") as scratch:
        request = Path(scratch) / "request.json"
        response = Path(scratch) / "response.json"
        request.write_text(
            json.dumps(
                {
                    "execution": execution,
                    "plan_kwargs": dict(plan_kwargs),
                    "session_id": session_id,
                },
                default=str,
            )
        )
        completed = runner(
            [str(runtime.python), "-I", "-m", HANDOFF_MODULE, str(request), str(response)],
            env=env,
            check=False,
            # The parent prints the one plan result on stdout; progress is stderr.
            stdout=sys.stderr,
        )
        try:
            payload = json.loads(response.read_text())
        except (OSError, ValueError):
            payload = None
    if not isinstance(payload, dict) or not (
        isinstance(payload.get("result"), dict) or payload.get("error")
    ):
        raise QaPlanExecutionError(
            f"qa_controller_handoff_failed: candidate runtime {runtime.root} exited "
            f"{completed.returncode} without a plan result for execution "
            f"{execution_id}. Its output above names the cause; the execution keeps "
            "its custody, so resume it with `yoke qa plan run --resume-execution-id "
            f"{execution_id}` and the same subject flags after repairing it"
        )
    if payload.get("error"):
        raise QaPlanExecutionError(str(payload["error"]))
    result = dict(payload["result"])
    result[CONTROLLER_RUNTIME_KEY] = {
        **dict(result.get(CONTROLLER_RUNTIME_KEY) or {}),
        "executable": str(runtime.executable),
    }
    return result


def main(argv: list[str] | None = None) -> int:
    """Candidate-side entry: adopt the begun execution and run it."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print(f"usage: python -m {HANDOFF_MODULE} REQUEST RESPONSE", file=sys.stderr)
        return 2
    request, response = Path(args[0]), Path(args[1])
    data = json.loads(request.read_text())
    from yoke_contracts.runtime_ports.structured_dispatch import get_structured_dispatch
    from yoke_core.domain.qa_plan_execution import execute_plan

    actor = get_structured_dispatch().build_actor(session_id=data.get("session_id") or None)
    try:
        # One execution only: the installed controller drives further partitions.
        result = execute_plan.__wrapped__(
            **data["plan_kwargs"], adopted_execution=data["execution"], actor=actor
        )
    except QaPlanExecutionError as exc:
        response.write_text(json.dumps({"error": str(exc)}))
        return 2
    result = {**result, CONTROLLER_RUNTIME_KEY: controller_runtime_identity()}
    response.write_text(json.dumps({"result": result}, default=str))
    return 0


__all__ = ["hand_off", "main", "provision"]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
