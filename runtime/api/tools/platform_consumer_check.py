"""Reach the hosted consumer's own compatibility check and read its verdict.

The consumer project owns what "compatible" means; this module owns only
how to ask it about one exact candidate and how to classify the answer. It
is deliberately not a validator — nothing here inspects a contract version,
builds anything, or decides compatibility on its own.

The invocation contract is agreed with the consumer side: a dispatch-only
workflow taking the full candidate commit plus Yoke's correlation input,
answering through the run conclusion, and naming the revision it proved in
the run's head commit. Changing any name here is a change to both repos.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any, Dict, Optional, Sequence, Tuple

from yoke_contracts.api_urls import HOSTED_PROD_API_URL
from yoke_contracts.github_workflow_dispatch import (
    WORKFLOW_DISPATCH_CORRELATION_INPUT,
)

CONSUMER_REPO = "upyoke/platform"
CONSUMER_PROJECT = "platform"
CONSUMER_CHECK_WORKFLOW = "platform-product-compatibility.yml"
#: The consumer trunk, and the default thing to prove against.
CONSUMER_TRUNK_REF = "main"
CANDIDATE_INPUT = "product_ref"

#: Scoped API token for the consumer project's GitHub binding. Absent on a
#: fork, where no scoped credential is ever exposed.
CONSUMER_TOKEN_ENV = "YOKE_PLATFORM_RELEASE_API_TOKEN"

#: A connection of its own, so binding it never disturbs whichever
#: authority the caller had already selected for its other steps.
CONSUMER_CONNECTION = "platform-consumer-check"

FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
COMMAND_TIMEOUT_SECONDS = 300

#: The consumer refused the candidate, or its evidence does not name it.
UNPROVEN = 1
#: No verdict could be obtained at all.
UNAVAILABLE = 2


def _detail(stdout: str, stderr: str) -> str:
    parts = [text.strip() for text in (stderr, stdout) if text.strip()]
    return " | ".join(parts) or "no output"


def _yoke(
    argv: Sequence[str], *, timeout: int, stdin: Optional[str] = None,
) -> Tuple[int, str, str]:
    """Run one `yoke` command against the consumer connection."""
    env = dict(os.environ)
    env["YOKE_ENV"] = CONSUMER_CONNECTION
    try:
        completed = subprocess.run(
            ["yoke", *argv],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, "", f"`yoke {' '.join(argv[:2])}` could not run: {exc}"
    return completed.returncode, completed.stdout, completed.stderr


def bind_consumer_authority() -> str:
    """Bind the scoped consumer authority, or say why it is unavailable."""
    token = os.environ.get(CONSUMER_TOKEN_ENV, "").strip()
    if not token:
        return (
            f"no scoped consumer credential in {CONSUMER_TOKEN_ENV}. A fork "
            "never receives one, so this pair can only be proven from a "
            "branch in the product repository; ask a maintainer to run the "
            "check there."
        )
    code, stdout, stderr = _yoke(
        [
            "connection",
            "set",
            CONSUMER_CONNECTION,
            "--transport",
            "https",
            "--prod",
            "--api-url",
            HOSTED_PROD_API_URL,
            "--token-stdin",
        ],
        timeout=COMMAND_TIMEOUT_SECONDS,
        stdin=token,
    )
    if code != 0:
        return (
            "consumer authority could not be bound: " + _detail(stdout, stderr)
        )
    return ""


def dispatch(
    candidate_sha: str, dispatch_key: str, consumer_ref: str = CONSUMER_TRUNK_REF,
) -> Tuple[str, str]:
    """Dispatch — or recover — the consumer run for this exact candidate.

    The request id carries the candidate and the consumer branch, so a retry
    inside one attempt rejoins the run that tested that pair while neither a
    different candidate nor a different consumer branch can adopt it.

    *consumer_ref* is a branch or tag, because that is all a workflow
    dispatch accepts; naming a companion branch is how a breaking pair is
    proven before either half is on trunk. The exact revision it resolved to
    comes back as the run's head commit.
    """
    code, stdout, stderr = _yoke(
        [
            "github-actions",
            "trigger",
            CONSUMER_REPO,
            CONSUMER_CHECK_WORKFLOW,
            "--ref",
            consumer_ref,
            "--input",
            f"{CANDIDATE_INPUT}={candidate_sha}",
            "--request-id",
            f"consumer-compat:{candidate_sha}:{consumer_ref}:{dispatch_key}",
            "--correlation-input",
            WORKFLOW_DISPATCH_CORRELATION_INPUT,
            "--project",
            CONSUMER_PROJECT,
        ],
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    if code != 0:
        return "", f"consumer check could not be dispatched: {_detail(stdout, stderr)}"
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        return "", "consumer check dispatch named no run to read"
    return lines[0], ""


def await_verdict(run_id: str, *, timeout_sec: int) -> Tuple[Dict[str, Any], str]:
    """The consumer run's terminal verdict, or why it could not be read."""
    code, stdout, stderr = _yoke(
        [
            "github-actions",
            "wait-run",
            CONSUMER_REPO,
            run_id,
            "--project",
            CONSUMER_PROJECT,
            "--timeout",
            str(timeout_sec),
            "--json",
        ],
        timeout=timeout_sec + COMMAND_TIMEOUT_SECONDS,
    )
    if code == -1:
        return {}, stderr
    try:
        payload = json.loads(stdout)
    except ValueError:
        return {}, f"consumer verdict unreadable: {_detail(stdout, stderr)}"
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        return {}, f"consumer verdict malformed: {_detail(stdout, stderr)}"
    return result, ""


def classify(
    result: Dict[str, Any], *, candidate_sha: str, run_id: str,
) -> Tuple[int, str, str]:
    """Exit code, narrative, and the consumer revision actually proven.

    The revision is empty on every non-zero code: nothing was proven, so
    there is nothing later stages may bind themselves to.
    """
    where = str(result.get("html_url") or "").strip() or f"run {run_id}"
    state = str(result.get("state") or "").strip()
    consumer_sha = str(result.get("head_sha") or "").strip()
    if state == "timeout":
        return UNAVAILABLE, (
            f"consumer compatibility unproven: {where} had not concluded "
            "within the wait budget. The candidate stays unproven until it "
            "does; re-running this check rejoins the same consumer run."
        ), ""
    if state != "success":
        conclusion = str(result.get("conclusion") or state or "unknown")
        against = consumer_sha or "an unnamed revision"
        return UNPROVEN, (
            f"the hosted consumer refused this candidate: product "
            f"{candidate_sha} against consumer {against} concluded "
            f"{conclusion} — {where}. The paired consumer adaptation is a "
            f"linked companion item in the {CONSUMER_PROJECT} project and "
            "has to land before this change is deliverable; an instruction "
            "that excludes redesigning the consumer never waives adapting it."
        ), ""
    if not FULL_SHA.match(consumer_sha):
        return UNPROVEN, (
            f"consumer evidence names no revision it proved: {where} "
            "concluded success without a readable head commit, so it cannot "
            f"be attributed to product {candidate_sha}. That is unproven, "
            "not proven; re-run the check."
        ), ""
    return 0, (
        f"hosted consumer builds against this candidate: product "
        f"{candidate_sha} with consumer {consumer_sha} — {where}"
    ), consumer_sha


def prove(
    candidate_sha: str,
    *,
    dispatch_key: str,
    timeout_sec: int,
    consumer_ref: str = CONSUMER_TRUNK_REF,
) -> Tuple[int, str, str]:
    """Bind, dispatch, wait, classify — code, narrative, proven revision."""
    unavailable = bind_consumer_authority()
    if unavailable:
        return UNAVAILABLE, f"consumer compatibility unproven: {unavailable}", ""
    run_id, dispatch_error = dispatch(candidate_sha, dispatch_key, consumer_ref)
    if dispatch_error:
        return UNAVAILABLE, f"consumer compatibility unproven: {dispatch_error}", ""
    print(
        f"consumer check run: {CONSUMER_REPO} run {run_id} at {consumer_ref}",
        flush=True,
    )
    result, unreadable = await_verdict(run_id, timeout_sec=timeout_sec)
    if unreadable:
        return UNAVAILABLE, f"consumer compatibility unproven: {unreadable}", ""
    return classify(result, candidate_sha=candidate_sha, run_id=run_id)


__all__ = [
    "CANDIDATE_INPUT",
    "COMMAND_TIMEOUT_SECONDS",
    "CONSUMER_CHECK_WORKFLOW",
    "CONSUMER_TRUNK_REF",
    "CONSUMER_CONNECTION",
    "CONSUMER_PROJECT",
    "CONSUMER_REPO",
    "CONSUMER_TOKEN_ENV",
    "FULL_SHA",
    "UNAVAILABLE",
    "UNPROVEN",
    "await_verdict",
    "bind_consumer_authority",
    "classify",
    "dispatch",
    "prove",
]
