"""Dispatch an exact Yoke/Platform pair using the release gate's payload."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

from runtime.api.tools.platform_consumer_dispatch_ref import (
    bound_dispatch_ref,
    consumer_dispatch_tag,
)
from yoke_contracts.github_workflow_dispatch import WORKFLOW_DISPATCH_CORRELATION_INPUT

CONSUMER_REPO = "upyoke/platform"
CONSUMER_PROJECT = "platform"
CONSUMER_CHECK_WORKFLOW = "platform-release-pin-check.yml"
CANDIDATE_INPUT = "product_ref"


def pair_request_id(candidate_sha: str, consumer_sha: str) -> str:
    """Identical pairs join; different commits never adopt that proof."""
    return (
        f"consumer-compat:{candidate_sha}:{consumer_dispatch_tag(consumer_sha)}:"
        f"{CONSUMER_CHECK_WORKFLOW}"
    )


def build_dispatch(candidate_sha: str, consumer_sha: str) -> list[str]:
    """Own every input that contributes to exact-pair dispatch identity."""
    return [
        "github-actions", "trigger", CONSUMER_REPO, CONSUMER_CHECK_WORKFLOW,
        "--ref", consumer_dispatch_tag(consumer_sha),
        "--input", f"{CANDIDATE_INPUT}={candidate_sha}",
        "--input", f"consumer_sha={consumer_sha}",
        "--request-id", pair_request_id(candidate_sha, consumer_sha),
        "--correlation-input", WORKFLOW_DISPATCH_CORRELATION_INPUT,
        "--project", CONSUMER_PROJECT,
    ]


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
        _, error = bound_dispatch_ref(
            _run, repo=CONSUMER_REPO, project=CONSUMER_PROJECT,
            sha=consumer, timeout=300,
        )
        if error:
            print(error, file=sys.stderr)
            return 2
        code, stdout, stderr = _run(build_dispatch(candidate, consumer), timeout=300)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"consumer_dispatch_unavailable: {exc}; restore the yoke command and retry this pair", file=sys.stderr)
        return 2
    if stdout:
        print(stdout, end="")
    if stderr:
        print(stderr, end="", file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
