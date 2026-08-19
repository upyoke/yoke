"""Report what the landing gate would decide for one project, right now.

An operator-facing read: the gate refuses a merge, so being able to ask
it directly — against the live ruleset, without attempting a merge — is
how its verdict gets confirmed before a landing depends on it.
"""

from __future__ import annotations

import argparse
import sys

from yoke_core.domain.merge_queue_live_drift import drift_blocking_landing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="merge_queue_gate_probe")
    parser.add_argument("--project", required=True)
    parser.add_argument("--checkout", required=True)
    parser.add_argument("--branch", default="main")
    args = parser.parse_args(argv)

    report = drift_blocking_landing(
        args.project, checkout=args.checkout, branch=args.branch,
    )
    print(f"would_block={report.drifted}")
    for line in report.drift:
        print(f"  drift: {line}")
    for line in report.unreadable:
        print(f"  unverified: {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
