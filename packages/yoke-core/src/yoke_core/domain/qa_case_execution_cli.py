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
    parsed = parser.parse_args(args)
    if bool(parsed.expected_branch) != bool(parsed.expected_sha):
        parser.error("--expected-branch and --expected-sha must be paired")
    try:
        result = execute_case(
            parsed.requirement_id,
            base_url=parsed.base_url,
            expected_branch=parsed.expected_branch,
            expected_sha=parsed.expected_sha,
            timeout_seconds=parsed.timeout_seconds,
        )
    except QaCaseExecutionError as exc:
        print(f"yoke qa case run: {exc}", file=sys.stderr)
        return 2
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
