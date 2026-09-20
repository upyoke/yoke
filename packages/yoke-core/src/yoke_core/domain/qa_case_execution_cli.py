"""Engine-owned CLI for one materialized QA plan case."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from yoke_core.domain.qa_case_execution import (
    QaCaseExecutionError,
    execute_case,
)

WAITING_RETRY_EXIT = 3


def _report_outcome(result: dict) -> None:
    """Restate the verdict on stderr, naming where to re-read the run.

    The JSON on stdout is for machines. A human or agent reading the
    terminal after a long gate run needs the verdict, the exit code, and
    the capture path without parsing it — especially on a failure, where
    the alternative is re-running the same command by hand to see why.

    A timed-out run adds a second line: its verdict is the same ``fail`` a
    broken branch reports, so the reader is told which one happened.

    A CI-routed case also names ``ci_run_source``, because a verdict this
    invocation adopted from a run that had already concluded reads
    identically to one it waited 14 minutes for unless the line says so.
    """
    fields = [
        f"verdict={result.get('verdict')}",
        f"outcome={result.get('case_outcome')}",
    ]
    if result.get("ci_run_source"):
        fields.append(f"ci_run_source={result['ci_run_source']}")
    if result.get("exit_code") is not None:
        fields.append(f"exit_code={result['exit_code']}")
    if result.get("output_capture"):
        fields.append(f"capture={result['output_capture']}")
    print(f"# qa case run: {' '.join(fields)}", file=sys.stderr, flush=True)
    if result.get("timeout_summary"):
        print(
            f"# qa case run: {result['timeout_summary']}",
            file=sys.stderr,
            flush=True,
        )


#: Which subject this command can credit, and which one it cannot. Read as
#: ``yoke qa case run --help``.
_EPILOG = """\
Which run earns which credit
----------------------------
This command executes exactly ONE requirement by id, and the credit lands on
whatever subject that requirement is already bound to. It is the right form for
an item's own verification gate -- the Command case that is a Dash item's single
full run.

It is NOT the form that credits a deployment stage. A deployment QA stage
credits only the requirements bound to its own stage name, and an item-scoped
stage needs the member named too, so reach for the stage-scoped plan run
instead; running cases one id at a time can pass every case while the stage
still reads unsatisfied:

  yoke qa plan run --deployment-run-id RUN --stage STAGE --member PREFIX-N --project P

Add `--plan PLAN` only for a stage that names no cases; a stage already naming
its own refuses it, because a plan there materializes a second, duplicate set
of obligations beside the ones the stage credits.

See `yoke qa plan run --help` for the full subject/scope matrix, and
`yoke merge item --help` for the close-out that follows a credited stage.
"""


def run(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa case run",
        description=(
            "Execute one materialized test-plan case through its declared "
            "registered runner. A Command case's method_config.command is a "
            "/bin/sh -c line, not a Python module body."
        ),
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--requirement-id", type=int, required=True)
    parser.add_argument(
        "--base-url",
        default="",
        help=(
            "HTTP(S) URL exported to the Command as BASE_URL, including a "
            "direct run-attached row that omits method_config.requires_base_url"
        ),
    )
    parser.add_argument("--expected-branch")
    parser.add_argument("--expected-sha")
    parser.add_argument("--timeout-seconds", type=int)
    parser.add_argument(
        "--checkout-path",
        help=(
            "Execute the case in this checkout instead of the default tree. "
            "For a deployment candidate, pin a separate tree to that revision."
        ),
    )
    parser.add_argument(
        "--allow-tree-mismatch",
        action="store_true",
        help=(
            "Run the case against the resolved checkout even when it sits "
            "outside this session's claim-bound worktree. The tree-binding "
            "refusal names this flag; it exists so that recovery is real."
        ),
    )
    parser.add_argument("--session-id")
    parsed = parser.parse_args(args)
    if bool(parsed.expected_branch) != bool(parsed.expected_sha):
        parser.error("--expected-branch and --expected-sha must be paired")
    from yoke_core.api.service_client_structured_api_adapter import build_actor

    actor = build_actor(session_id=parsed.session_id)
    try:
        result = execute_case(
            parsed.requirement_id,
            base_url=parsed.base_url,
            expected_branch=parsed.expected_branch,
            expected_sha=parsed.expected_sha,
            timeout_seconds=parsed.timeout_seconds,
            checkout_path=parsed.checkout_path,
            allow_tree_mismatch=parsed.allow_tree_mismatch,
            actor=actor,
        )
    except QaCaseExecutionError as exc:
        print(f"yoke qa case run: {exc}", file=sys.stderr)
        return 2
    _report_outcome(result)
    print(json.dumps(result, sort_keys=True))
    if result.get("case_outcome") == "waiting":
        return WAITING_RETRY_EXIT
    verdict = result.get("verdict")
    if verdict == "fail":
        return 1
    if verdict == "error":
        return 2
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    return run(list(sys.argv[1:] if argv is None else argv))


__all__ = ["WAITING_RETRY_EXIT", "main", "run"]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
