"""Continue a source-backed CI gate in fresh imports after its lane moves."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Optional

from yoke_contracts.api.function_call import ActorContext
from yoke_core.domain import qa_case_ci_lane, qa_case_ci_resume
from yoke_core.domain.qa_case_execution import QaCaseExecutionError


def resolve_checkout(case: dict, checkout_path: Optional[str | Path]) -> Path:
    if case.get("deployment_run_id"):
        raise QaCaseExecutionError(
            "deployment_ci_candidate_unverified: command-ci verifies an item "
            f"lane, not deployment run {case['deployment_run_id']!r}. No action was "
            "produced. Replace this post-deploy case with the command method "
            "and run the same stage/member QA plan; without --checkout-path "
            "that runner checks out the run's pinned candidate."
        )
    from yoke_core.domain.qa_case_execution import _execution_checkout

    source = checkout_path if checkout_path is not None else _execution_checkout(case)
    checkout = Path(source).resolve()
    if not checkout.is_dir():
        raise QaCaseExecutionError(f"CI execution checkout does not exist: {checkout}")
    return checkout


def prepare_lane(checkout: Path, *, prepared: dict | None, **kwargs):
    """A continued gate retains its prepared candidate without another rebase."""
    if prepared is not None:
        return qa_case_ci_resume.PreparedLane(queue_target=prepared["queue_target"])
    return qa_case_ci_resume.prepare_lane_preserving_covering_run(checkout, **kwargs)


def continue_updated_source(
    checkout: Path,
    previous_head_sha: str,
    lane,
    case: dict,
    *,
    prepared: dict | None,
    actor: ActorContext | None,
    **options,
) -> dict | None:
    """Restart only when the gate's own imported source changed under it.

    The authorized case and prepared queue target cross the interpreter boundary;
    no second begin, covering-run lookup, lane update or publication is needed.
    Installed wheels and gates updating another project's checkout stay in process.
    """
    if prepared is not None or not Path(__file__).resolve().is_relative_to(checkout):
        return None
    if (
        not previous_head_sha
        or qa_case_ci_lane.ref_sha(checkout, "HEAD") == previous_head_sha
    ):
        return None
    payload = {
        "case": case,
        "options": {
            **options,
            "checkout_path": str(checkout),
            "actor": actor.model_dump(mode="json") if actor is not None else None,
            "_prepared": {
                "queue_target": lane.queue_target,
                "previous_head_sha": previous_head_sha,
            },
        },
    }
    print(
        "# qa case run: source lane changed; continuing with fresh imports "
        "on the prepared candidate",
        file=sys.stderr,
        flush=True,
    )
    try:
        with tempfile.TemporaryDirectory(prefix="yoke-ci-continuation-") as directory:
            result_path = Path(directory) / "result.json"
            completed = subprocess.run(
                [sys.executable, "-m", __name__, str(result_path)],
                input=json.dumps(payload),
                text=True,
                cwd=checkout,
            )
            if completed.returncode or not result_path.is_file():
                raise ValueError(
                    f"fresh interpreter exited {completed.returncode} without a result"
                )
            result = json.loads(result_path.read_text())
            if not isinstance(result, dict):
                raise ValueError("fresh interpreter returned a non-object result")
            if result.get("error"):
                raise ValueError(result["error"])
            return result["result"]
    except (OSError, ValueError, KeyError) as exc:
        raise QaCaseExecutionError(
            f"qa_ci_source_restart_failed: {exc}. The lane update is preserved; "
            "rerun the same QA case from the updated lane. An existing CI run "
            "will be rejoined before another lane update."
        ) from exc


def main() -> int:
    # These imports belong to the new interpreter, after the source update.
    from yoke_core.domain.qa_case_ci_run import execute_ci_case

    payload = json.load(sys.stdin)
    options = payload["options"]
    if options["actor"] is not None:
        options["actor"] = ActorContext.model_validate(options["actor"])
    try:
        reply = {"result": execute_ci_case(payload["case"], **options)}
    except QaCaseExecutionError as exc:
        reply = {"error": str(exc)}
    Path(sys.argv[1]).write_text(json.dumps(reply))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
