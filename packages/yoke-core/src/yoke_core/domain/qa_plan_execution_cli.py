"""Engine-owned CLI for ordered materialized QA plan execution."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any, List, Optional

from yoke_core.domain.qa_case_execution_cli import WAITING_RETRY_EXIT
from yoke_core.domain.qa_plan_execution import (
    QaPlanExecutionError,
    execute_plan,
)

AGENT_REVIEW_REQUIRED_EXIT = 12

#: Result fields restated on stderr for a case that did not pass, as
#: ``label=value`` pairs after the requirement id.
_REPORTED_CASE_FIELDS = (
    ("case", "case_key"),
    ("outcome", "case_outcome"),
    ("verdict", "verdict"),
    ("exit_code", "exit_code"),
    ("error", "error"),
)


def _report_case_failures(result: dict[str, Any]) -> None:
    """Restate every case that did not pass, one line each, on stderr.

    A plan run ends on a single JSON document covering many cases, and the
    case that actually stopped the run is one entry inside it. The reader
    of the terminal gets the same treatment ``yoke qa case run`` gives its
    single verdict: which requirement, which case, and why — without
    parsing stdout or re-running the plan to find out.
    """
    from yoke_core.domain.qa_plan_execution_result_state import aggregate_state

    for case in result.get("results") or []:
        if not isinstance(case, dict) or aggregate_state("passed", case) == "passed":
            continue
        fields = [f"requirement={case.get('requirement_id')}"]
        fields.extend(
            f"{label}={case[key]}"
            for label, key in _REPORTED_CASE_FIELDS
            if case.get(key) not in (None, "")
        )
        print(f"# qa plan run: {' '.join(fields)}", file=sys.stderr, flush=True)


def _review_connection_env() -> str:
    explicit = os.environ.get("YOKE_ENV", "").strip()
    if explicit:
        return explicit
    from yoke_contracts.machine_config.runtime import active_env

    return active_env()


def _require_walker_dispatch_capability(
    result: dict[str, Any],
    *,
    harness_id: Optional[str] = None,
    target_root: Optional[Path] = None,
) -> None:
    """Refuse an informed walker whose actual harness adapter is readonly."""
    bundle = result.get("review_bundle")
    dispatch = bundle.get("dispatch") if isinstance(bundle, dict) else None
    walkers = dispatch.get("walker_dispatches") if isinstance(dispatch, dict) else None
    informed = [
        walker
        for walker in walkers or []
        if isinstance(walker, dict) and walker.get("executor") == "informed_subagent"
    ]
    if not informed:
        return
    if harness_id is None:
        from yoke_core.hooks.helpers_identity import (
            canonical_harness_id,
            detect_executor,
        )

        harness_id = canonical_harness_id(detect_executor())
    if harness_id != "cursor":
        return
    if target_root is None:
        from yoke_contracts.cursor_hook_root import (
            resolve_existing_hook_root_from_env,
        )

        target_root = Path(resolve_existing_hook_root_from_env())
    from yoke_core.domain.agents_render import CURSOR_NATIVE_AGENTS_DIR
    from yoke_core.domain.agents_render_cursor import (
        CursorAgentCapabilityError,
        load_rendered_cursor_spec,
        require_cursor_agent_write_capability,
    )

    adapter_path = Path(target_root) / CURSOR_NATIVE_AGENTS_DIR / "yoke-qa-walker.md"
    try:
        spec = load_rendered_cursor_spec(adapter_path)
        require_cursor_agent_write_capability("qa-walker", spec)
    except CursorAgentCapabilityError as exc:
        raise QaPlanExecutionError(str(exc)) from exc


def _qualify_review_dispatch(result: dict[str, Any]) -> None:
    bundle = result.get("review_bundle")
    if not isinstance(bundle, dict):
        return
    dispatch = bundle.get("dispatch")
    if not isinstance(dispatch, dict):
        raise QaPlanExecutionError("QA review bundle lacks a dispatch contract")
    authority = dispatch.get("authority")
    if not isinstance(authority, dict) or authority.get("state") != "bound":
        raise QaPlanExecutionError("QA review bundle lacks immutable target authority")
    connection_env = _review_connection_env()
    authority["connection_env"] = connection_env
    prefix = f"yoke --env {shlex.quote(connection_env)}"
    commands = dispatch.get("artifact_read_commands")
    if not isinstance(commands, list) or any(
        not isinstance(command, str) or not command.startswith("yoke ")
        for command in commands
    ):
        raise QaPlanExecutionError(
            "QA review bundle lacks typed artifact-read commands"
        )
    dispatch["artifact_read_commands"] = [
        command.replace("yoke ", f"{prefix} ", 1) for command in commands
    ]
    walkers = dispatch.get("walker_dispatches") or []
    if not isinstance(walkers, list):
        raise QaPlanExecutionError("QA review bundle has invalid walker dispatches")
    _require_walker_dispatch_capability(result)
    for walker in walkers:
        if not isinstance(walker, dict):
            raise QaPlanExecutionError("QA mission walker is not an object")
        for key in (
            "host_command",
            "browser_setup_command",
            "browser_step_command",
            "artifact_add_command",
        ):
            command = walker.get(key)
            if not isinstance(command, str) or not command.startswith("yoke "):
                label = key.replace("_", "-")
                raise QaPlanExecutionError(f"QA mission walker lacks a typed {label}")
            qualified = command.replace("yoke ", f"{prefix} ", 1)
            walker[key] = qualified
            walker["prompt"] = str(walker.get("prompt") or "").replace(
                command,
                qualified,
            )
    submit = dispatch.get("submit_command")
    if not isinstance(submit, str) or not submit.startswith("yoke "):
        raise QaPlanExecutionError(
            "QA review bundle lacks a typed verdict submission command"
        )
    dispatch["submit_command"] = submit.replace("yoke ", f"{prefix} ", 1)
    dispatch["prompt"] = (
        f"{str(dispatch.get('prompt') or '').strip()} Use the exact Yoke "
        f"connection `{connection_env}` carried by this handoff for every "
        "registered read and submission; do not use the ambient connection."
    )


#: The subject/scope matrix: which invocation credits which subject, and the
#: release-time form whose omission leaves a stage unsatisfied. Read as
#: ``yoke qa plan run --help``.
_EPILOG = """\
Pick the subject, then the scope
--------------------------------
Exactly one subject flag is required, and it decides everything else.

  --item PREFIX-N --transition TRANSITION
      An item's own attached plans, for a lifecycle transition's QA gate.
      Requires --transition; does not accept --plan, because an item uses the
      plans already attached to it.

  --deployment-run-id RUN --stage STAGE [--member PREFIX-N] [--plan PLAN]
      One frozen QA stage of a deployment run. The stage must be the run's
      active pinned QA stage.

Release-time scope: a stage credits only its own name
-----------------------------------------------------
A deployment QA stage is satisfied only by requirements bound to that stage's
own name -- and an item-scoped stage by requirements bound to the member too.
So the scope flags are not optional decoration:

  * Run-scoped stage  -> --stage STAGE, no --member.
  * Item-scoped stage -> --stage STAGE --member PREFIX-N. The run-wide form is
    refused here rather than recording a pass the stage would ignore.

Dropping --stage or --member is the failure that looks like success: cases run,
verdicts record, and the stage still reads unsatisfied because nothing credited
it. `yoke qa case run --requirement-id N` refuses an item-scoped binding
and names this command instead of exiting zero with an uncredited pass.

When the stage names no concrete cases, --plan records the executor's
project-owned selection -- and only then. A stage already naming its own cases
(pinned, frozen, member-attached, admitted, or directly authored) refuses
--plan by name: a plan there materializes a second, duplicate set of
obligations beside the ones the stage credits. The wake asking for a selection
prints --plan; every other wake omits it.
Materialization stamps the run's own deployed target
onto the cases, so a plan authored before this release still verifies it. A
deployment case is bound to the candidate the run deployed, not to your lane:
pass --checkout-path at a separate checkout pinned to that revision, or pass
--allow-tree-mismatch when the case reads nothing from the checkout.

Who runs it, and what follows
-----------------------------
The item owner parked at its release wait runs its own stage when the
deployment wake asks for it, then finishes with `yoke merge item PREFIX-N
--result ... --verification ...`. The steering seat drives the run and never
substitutes a run-wide pass for a member's stage. See `yoke merge item --help`
for the close-out and `yoke deployment-runs --help` for the run itself.
"""


def run(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa plan run",
        description=(
            "Execute a materialized transition's cases in immutable "
            "plan/case/baseline order through their registered runners."
        ),
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subject = parser.add_mutually_exclusive_group(required=True)
    subject.add_argument("--item")
    subject.add_argument("--deployment-run-id")
    parser.add_argument("--stage")
    parser.add_argument("--member")
    parser.add_argument("--transition")
    parser.add_argument("--plan")
    parser.add_argument("--project")
    parser.add_argument("--base-url", default="")
    parser.add_argument(
        "--machine",
        help="Pin Machine QA cases to one registered Test Machine.",
    )
    parser.add_argument("--expected-branch")
    parser.add_argument("--expected-sha")
    parser.add_argument("--timeout-seconds", type=int)
    parser.add_argument(
        "--checkout-path",
        help=(
            "Execute cases in this checkout; for a deployment candidate, "
            "pin a separate tree to that revision."
        ),
    )
    parser.add_argument(
        "--allow-tree-mismatch",
        action="store_true",
        help="Allow a resolved checkout outside this session's claimed worktree.",
    )
    parser.add_argument(
        "--continue-mission",
        action="store_true",
        help=(
            "Resume a mission walk the stale sweep settled while parked; "
            "refused unless the subject's most recent execution ended that way."
        ),
    )
    parser.add_argument("--session-id")
    parsed = parser.parse_args(args)
    if bool(parsed.expected_branch) != bool(parsed.expected_sha):
        parser.error("--expected-branch and --expected-sha must be paired")
    if parsed.item and not parsed.transition:
        parser.error("--item requires --transition")
    if parsed.item and parsed.plan:
        parser.error("--item uses attached plans and does not accept --plan")
    if parsed.deployment_run_id and not parsed.plan and not parsed.stage:
        parser.error("--deployment-run-id requires --plan")
    if parsed.deployment_run_id and parsed.transition:
        parser.error("--deployment-run-id does not accept --transition")
    if parsed.deployment_run_id and not parsed.project:
        parser.error("--deployment-run-id requires --project")
    if parsed.member and not parsed.stage:
        parser.error("--member requires --stage")

    from yoke_core.api.service_client_structured_api_adapter import build_actor

    actor = build_actor(session_id=parsed.session_id)
    try:
        result = execute_plan(
            public_ref=parsed.item,
            transition_id=parsed.transition,
            deployment_run_id=parsed.deployment_run_id,
            deployment_stage=parsed.stage,
            deployment_member=parsed.member,
            plan=parsed.plan,
            project=parsed.project,
            base_url=parsed.base_url,
            machine=parsed.machine,
            expected_branch=parsed.expected_branch,
            expected_sha=parsed.expected_sha,
            timeout_seconds=parsed.timeout_seconds,
            checkout_path=parsed.checkout_path,
            allow_tree_mismatch=parsed.allow_tree_mismatch,
            continue_mission=parsed.continue_mission,
            actor=actor,
        )
    except QaPlanExecutionError as exc:
        print(f"yoke qa plan run: {exc}", file=sys.stderr)
        return 2
    if result.get("state") == "awaiting_agent_review":
        try:
            _qualify_review_dispatch(result)
        except QaPlanExecutionError as exc:
            print(f"yoke qa plan run: {exc}", file=sys.stderr)
            return 2
    _report_case_failures(result)
    print(json.dumps(result, sort_keys=True))
    state = result.get("state")
    if state == "waiting":
        return WAITING_RETRY_EXIT
    if state == "awaiting_agent_review":
        print(
            "QA capture complete; dispatch the returned typed reviewer contract "
            "now and submit its complete verdict batch before continuing.",
            file=sys.stderr,
        )
        return AGENT_REVIEW_REQUIRED_EXIT
    if state in {"failed", "needs_review", "blocked_on_precondition"}:
        return 1
    if state == "error":
        return 2
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    return run(list(sys.argv[1:] if argv is None else argv))


__all__ = ["AGENT_REVIEW_REQUIRED_EXIT", "main", "run"]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
