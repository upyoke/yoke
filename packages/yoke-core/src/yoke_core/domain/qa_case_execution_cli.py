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
    """
    fields = [
        f"verdict={result.get('verdict')}",
        f"outcome={result.get('case_outcome')}",
    ]
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


def run(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa case run",
        description=(
            "Execute one materialized test-plan case through its declared "
            "registered executor."
        ),
    )
    parser.add_argument("--requirement-id", type=int, required=True)
    parser.add_argument("--base-url", default="")
    parser.add_argument("--expected-branch")
    parser.add_argument("--expected-sha")
    parser.add_argument("--timeout-seconds", type=int)
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
