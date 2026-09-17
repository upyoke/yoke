"""Complete a browser QA run with the commit it actually verified.

``recorded_head_sha`` reads ``raw_result.verification_tree.head_sha``; the
browser substrate writes only artifact handles there, so a visual pass
recorded without this names no commit and cannot prove exact-head
coverage. ``qa.run.complete`` replaces ``raw_result`` wholesale, so the
identity has to be merged into the substrate's own payload rather than
written over it.

    yoke dev run -- python3 -m runtime.api.tools.record_browser_case_verdict \
        --requirement-id N --run-id N --verdict pass --reason TEXT \
        --head-sha SHA [--branch NAME]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys


def _existing_raw_result(run_id: int) -> dict:
    read = subprocess.run(
        ["yoke", "db", "read",
         f"SELECT raw_result FROM qa_runs WHERE id = {int(run_id)}"],
        capture_output=True, text=True, check=True,
    )
    rows = json.loads(read.stdout)["rows"]
    if not rows:
        raise SystemExit(f"no qa_runs row {run_id}")
    raw = rows[0][0]
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirement-id", type=int, required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--verdict", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--branch", default="")
    arguments = parser.parse_args()

    payload = _existing_raw_result(arguments.run_id)
    # The substrate's own record is kept whole; the identity joins it.
    payload["verification_tree"] = {
        "head_sha": arguments.head_sha,
        **({"branch": arguments.branch} if arguments.branch else {}),
    }
    completed = subprocess.run(
        ["yoke", "qa", "run", "complete",
         "--requirement-id", str(arguments.requirement_id),
         "--run-id", str(arguments.run_id),
         "--verdict", arguments.verdict,
         "--verdict-reason", arguments.reason,
         "--raw-result", json.dumps(payload),
         "--json"],
        capture_output=True, text=True,
    )
    sys.stderr.write(completed.stderr)
    print(completed.stdout.strip()[:400])
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
