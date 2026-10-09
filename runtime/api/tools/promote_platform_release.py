"""Dispatch and await the consumer's release promotion against a current proof.

Each attempt first follows the consumer trunk
(:mod:`runtime.api.tools.follow_moved_platform_consumer`), then dispatches the
consumer's promotion with the revision that follow proved, and awaits it. The
trunk can still move in the seconds between that read and the moment the
promotion binds itself to its source, which the promotion refuses before it
publishes or deploys anything. Only that refusal earns another attempt —
bounded, and each one re-reads and re-proves — so a promotion that failed for
any other reason is reported as it failed, never repeated.

Usage::

    python3 -m runtime.api.tools.promote_platform_release \\
        --candidate-sha <40-hex> --proven-consumer-sha <40-hex> \\
        --product-ref <tag> --release-mode normal|hotfix \\
        --target-environment stage|prod --request-id <id>

Writes ``run_id`` (the promotion run that succeeded) to ``$GITHUB_OUTPUT``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from typing import Any, Dict, Optional, Sequence, Tuple

from runtime.api.tools.follow_moved_platform_consumer import MOVED_AGAIN, follow
from runtime.api.tools.require_platform_consumer_compatibility import (
    CONSUMER_PROJECT,
    CONSUMER_REPO,
    CONSUMER_TRUNK_REF,
    _detail,
    _write_output,
    is_full_commit_sha,
)

PROMOTION_WORKFLOW = "yoke-release-promote.yml"
#: The first attempt plus two retries.
MAX_ATTEMPTS = 3
DISPATCH_RECOVERY_ATTEMPTS = 12
DISPATCH_RECOVERY_SECONDS = 5
PROMOTION_TIMEOUT_SECONDS = 10800
PROOF_TIMEOUT_SECONDS = 1800
_COMMAND_TIMEOUT_SECONDS = 300

#: The promotion's own refusal when the trunk it would incorporate is not the
#: revision it was handed; followed by that revision.
BIND_REFUSAL_MARKER = "but the pair was proven at "


def _yoke(argv: Sequence[str], *, timeout: int) -> Tuple[int, str, str]:
    """Run one `yoke` command on the connection this step selected."""
    try:
        completed = subprocess.run(
            ["yoke", *argv],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, "", f"`yoke {' '.join(argv[:2])}` could not run: {exc}"
    return completed.returncode, completed.stdout, completed.stderr


def attempt_request_id(request_id: str, attempt: int) -> str:
    """The first attempt keeps the caller's id; each retry is its own intent."""
    return request_id if attempt == 1 else f"{request_id}:follow-{attempt}"


def dispatch(inputs: Dict[str, str], request_id: str) -> Tuple[str, str]:
    """Dispatch or recover one promotion run; ``(run_id, error)``."""
    argv = [
        "github-actions",
        "trigger",
        CONSUMER_REPO,
        PROMOTION_WORKFLOW,
        "--ref",
        CONSUMER_TRUNK_REF,
    ]
    for key, value in inputs.items():
        argv += ["--input", f"{key}={value}"]
    argv += [
        "--request-id",
        request_id,
        "--correlation-input",
        "yoke_dispatch_id",
        "--project",
        CONSUMER_PROJECT,
    ]
    for recovery in range(1, DISPATCH_RECOVERY_ATTEMPTS + 1):
        code, stdout, stderr = _yoke(argv, timeout=_COMMAND_TIMEOUT_SECONDS)
        lines = [line.strip() for line in stdout.splitlines() if line.strip()]
        if code == 0 and lines:
            return lines[0], ""
        if "workflow_dispatch_ambiguous" not in stderr:
            return "", f"promotion dispatch refused: {_detail(stdout, stderr)}"
        # The server already recorded durable intent; the same request id and
        # payload discover the correlated run without posting another.
        print(stderr.strip(), file=sys.stderr)
        if recovery < DISPATCH_RECOVERY_ATTEMPTS:
            time.sleep(DISPATCH_RECOVERY_SECONDS)
    return "", "promotion dispatch remained ambiguous after bounded recovery"


def await_run(run_id: str) -> Dict[str, Any]:
    """The promotion run's terminal result; empty when it could not be read."""
    code, stdout, stderr = _yoke(
        [
            "github-actions",
            "wait-run",
            CONSUMER_REPO,
            run_id,
            "--project",
            CONSUMER_PROJECT,
            "--timeout",
            str(PROMOTION_TIMEOUT_SECONDS),
            "--json",
        ],
        timeout=PROMOTION_TIMEOUT_SECONDS + _COMMAND_TIMEOUT_SECONDS,
    )
    try:
        result = (json.loads(stdout) or {}).get("result")
    except (ValueError, AttributeError):
        result = None
    if not isinstance(result, dict):
        print(
            f"promotion verdict unreadable: {_detail(stdout, stderr)}", file=sys.stderr
        )
        return {}
    return result


def refused_moved_trunk(run_id: str, proven_sha: str) -> bool:
    """Whether the run failed only because the trunk moved past ``proven_sha``."""
    code, stdout, stderr = _yoke(
        [
            "github-actions",
            "failed-log",
            CONSUMER_REPO,
            run_id,
            "--project",
            CONSUMER_PROJECT,
            "--json",
        ],
        timeout=_COMMAND_TIMEOUT_SECONDS,
    )
    try:
        jobs = ((json.loads(stdout) or {}).get("result") or {}).get("jobs") or []
    except (ValueError, AttributeError):
        jobs = []
    if code != 0 or not jobs:
        print(
            f"promotion failure log unreadable: {_detail(stdout, stderr)}",
            file=sys.stderr,
        )
        return False
    marker = BIND_REFUSAL_MARKER + proven_sha
    return any(marker in str(job.get("region") or "") for job in jobs)


def promote(args: argparse.Namespace) -> int:
    proven = args.proven_consumer_sha
    for attempt in range(1, MAX_ATTEMPTS + 1):
        code, narrative, followed = follow(
            args.candidate_sha,
            proven,
            timeout_sec=PROOF_TIMEOUT_SECONDS,
        )
        print(narrative, file=sys.stderr if code else sys.stdout, flush=True)
        if code == MOVED_AGAIN and attempt < MAX_ATTEMPTS:
            continue
        if code:
            return code
        proven = followed
        run_id, error = dispatch(
            {
                "target_environment": args.target_environment,
                "product_ref": args.product_ref,
                "release_mode": args.release_mode,
                "proven_consumer_sha": proven,
            },
            attempt_request_id(args.request_id, attempt),
        )
        if error:
            print(error, file=sys.stderr)
            return 1
        print(
            f"Platform release run: https://github.com/{CONSUMER_REPO}/actions/runs/{run_id}",
            flush=True,
        )
        result = await_run(run_id)
        if result.get("state") == "success":
            _write_output("run_id", run_id)
            return 0
        if attempt < MAX_ATTEMPTS and refused_moved_trunk(run_id, proven):
            print(
                f"promotion run {run_id} refused because {CONSUMER_TRUNK_REF} "
                f"moved past {proven} before it bound; following it again "
                f"(attempt {attempt + 1} of {MAX_ATTEMPTS})",
                flush=True,
            )
            continue
        print(
            f"promotion run {run_id} did not succeed "
            f"({result.get('conclusion') or result.get('state') or 'unread'}); "
            "inspect that run, correct it, and retry the deployment run",
            file=sys.stderr,
        )
        return 1
    print(
        f"consumer {CONSUMER_TRUNK_REF} kept moving across {MAX_ATTEMPTS} "
        "attempts; retry once it is quiet, or start a new deployment run",
        file=sys.stderr,
    )
    return 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="promote_platform_release",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--proven-consumer-sha", required=True)
    parser.add_argument("--product-ref", required=True)
    parser.add_argument("--release-mode", required=True)
    parser.add_argument(
        "--target-environment", required=True, choices=("stage", "prod")
    )
    parser.add_argument("--request-id", required=True)
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    args.candidate_sha = args.candidate_sha.strip().lower()
    args.proven_consumer_sha = args.proven_consumer_sha.strip().lower()
    for name in ("candidate_sha", "proven_consumer_sha"):
        if not is_full_commit_sha(getattr(args, name)):
            print(
                f"--{name.replace('_', '-')} must be a full 40-hex commit, got "
                f"{getattr(args, name)!r}; the pre-tag proof writes it",
                file=sys.stderr,
            )
            return 2
    return promote(args)


if __name__ == "__main__":
    raise SystemExit(main())
