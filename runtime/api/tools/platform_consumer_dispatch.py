"""Dispatch an exact Yoke/Platform pair using the release gate's payload."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

from yoke_core.domain import platform_consumer_dispatch as pairs


def _run(argv, *, timeout):
    result = subprocess.run(
        ["yoke", *argv], capture_output=True, text=True, timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--consumer-sha", required=True)
    args = parser.parse_args(argv)
    candidate = args.candidate_sha.strip().lower()
    consumer = args.consumer_sha.strip().lower()
    if not all(re.fullmatch(r"[0-9a-f]{40}", value) for value in (candidate, consumer)):
        print("consumer_pair_invalid: supply full 40-hex candidate and consumer commits", file=sys.stderr)
        return 2
    try:
        run_id, error = pairs.dispatch_pair(_run, candidate, consumer)
        if error:
            print(error, file=sys.stderr)
            return 2
        print(run_id)
        return 0
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"consumer_dispatch_unavailable: {exc}; restore the yoke command and retry this pair", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
