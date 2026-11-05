"""Start or join exact-pair consumer proof without waiting for its verdict."""

from __future__ import annotations

import time
from typing import Tuple
from yoke_contracts.github_workflow_dispatch import WORKFLOW_DISPATCH_CORRELATION_INPUT
from yoke_core.domain.platform_consumer_dispatch_ref import bound_dispatch_ref, consumer_dispatch_tag

_COMMAND_TIMEOUT_SECONDS = 300
_PENDING_JOIN_CODE = "workflow_dispatch_pending"
_PENDING_JOIN_BUDGET_SECONDS = 120.0


def _detail(stdout: str, stderr: str) -> str:
    return " | ".join(text.strip() for text in (stderr, stdout) if text.strip()) or "no output"


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



def dispatch_pair(run_yoke, candidate_sha: str, consumer_sha: str) -> Tuple[str, str]:
    """Dispatch or join proof at the immutable bound consumer commit."""
    _, error = bound_dispatch_ref(
        run_yoke,
        repo=CONSUMER_REPO,
        project=CONSUMER_PROJECT,
        sha=consumer_sha,
        timeout=_COMMAND_TIMEOUT_SECONDS,
    )
    if error:
        return "", error
    trigger = build_dispatch(candidate_sha, consumer_sha)
    deadline = time.monotonic() + _PENDING_JOIN_BUDGET_SECONDS
    delay = 2.0
    while True:
        code, stdout, stderr = run_yoke(trigger, timeout=_COMMAND_TIMEOUT_SECONDS)
        if code == 0 or _PENDING_JOIN_CODE not in f"{stderr}\n{stdout}":
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        print("consumer check join is pending; retrying same request_id", flush=True)
        time.sleep(min(delay, remaining))
        delay = min(delay * 2, 30.0)
    if code != 0:
        return "", f"consumer check could not be dispatched: {_detail(stdout, stderr)}"
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        return "", "consumer check dispatch named no run to read"
    return lines[0], ""

