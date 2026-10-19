"""Refuse to publish a release the hosted consumer has not been built against.

Pass full --candidate-sha and --consumer-sha commits. An immutable consumer
tag binds workflow source, so the main-push proof, retries and simultaneous
stage/prod releases of one exact pair join one consumer run.

On success it writes ``proven_consumer_sha`` to ``$GITHUB_OUTPUT``.
Exits 0 when proven, 1 when refused or unattributable, 2 when unavailable.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Any, Dict, Optional, Sequence, Tuple

from runtime.api.tools.platform_consumer_dispatch_ref import (
    bound_dispatch_ref,
    consumer_dispatch_tag,
)
from runtime.api.tools.platform_consumer_run_wait import wait_run
from yoke_contracts.api_urls import HOSTED_PROD_API_URL
from yoke_contracts.github_workflow_dispatch import (
    WORKFLOW_DISPATCH_CORRELATION_INPUT,
)

CONSUMER_REPO = "upyoke/platform"
CONSUMER_PROJECT = "platform"
CONSUMER_CHECK_WORKFLOW = "platform-release-pin-check.yml"
#: Advisory runs follow trunk; exact-pair runs use an immutable commit tag.
CONSUMER_TRUNK_REF = "main"
CANDIDATE_INPUT = "product_ref"

CONSUMER_TOKEN_ENV = "YOKE_PLATFORM_RELEASE_API_TOKEN"

CONSUMER_CONNECTION = "platform-consumer-check"

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_COMMAND_TIMEOUT_SECONDS = 300


def pair_request_id(candidate_sha: str, consumer_sha: str) -> str:
    """Identical pairs join; different commits never adopt that proof."""
    return (
        f"consumer-compat:{candidate_sha}:{consumer_dispatch_tag(consumer_sha)}:"
        f"{CONSUMER_CHECK_WORKFLOW}"
    )


UNPROVEN = 1
UNAVAILABLE = 2


def is_full_commit_sha(value: str) -> bool:
    """Whether *value* is a full 40-hex commit the consumer cannot re-resolve."""
    return bool(_FULL_SHA.match(str(value or "").strip().lower()))


def _detail(stdout: str, stderr: str) -> str:
    parts = [text.strip() for text in (stderr, stdout) if text.strip()]
    return " | ".join(parts) or "no output"


def _yoke(
    argv: Sequence[str],
    *,
    timeout: int,
    stdin: Optional[str] = None,
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
            f"{CONSUMER_TOKEN_ENV} is CI-only for this helper's bootstrap; "
            "the release train provides it. Local verification uses "
            "`yoke github-actions trigger` on the authenticated project route."
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
        timeout=_COMMAND_TIMEOUT_SECONDS,
        stdin=token,
    )
    if code != 0:
        return "consumer authority could not be bound: " + _detail(stdout, stderr)
    return ""


def dispatch(
    candidate_sha: str,
    consumer_sha: str,
    *,
    exact_pair: bool = True,
    request_id: str = "",
) -> Tuple[str, str]:
    """Dispatch the bound consumer commit; advisory calls follow trunk."""
    ref = CONSUMER_TRUNK_REF
    if exact_pair:
        ref, error = bound_dispatch_ref(
            _yoke,
            repo=CONSUMER_REPO,
            project=CONSUMER_PROJECT,
            sha=consumer_sha,
            timeout=_COMMAND_TIMEOUT_SECONDS,
        )
        if error:
            return "", error
        request_id = pair_request_id(candidate_sha, consumer_sha)
    code, stdout, stderr = _yoke(
        [
            "github-actions",
            "trigger",
            CONSUMER_REPO,
            CONSUMER_CHECK_WORKFLOW,
            "--ref",
            ref,
            "--input",
            f"{CANDIDATE_INPUT}={candidate_sha}",
            "--request-id",
            request_id,
            "--correlation-input",
            WORKFLOW_DISPATCH_CORRELATION_INPUT,
            "--project",
            CONSUMER_PROJECT,
        ],
        timeout=_COMMAND_TIMEOUT_SECONDS,
    )
    if code != 0:
        return "", f"consumer check could not be dispatched: {_detail(stdout, stderr)}"
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        return "", "consumer check dispatch named no run to read"
    return lines[0], ""


def await_verdict(run_id: str, *, timeout_sec: int) -> Tuple[Dict[str, Any], str]:
    """The consumer run's terminal verdict, or why it could not be read."""
    code, stdout, stderr = wait_run(
        _yoke,
        repo=CONSUMER_REPO,
        project=CONSUMER_PROJECT,
        run_id=run_id,
        timeout_sec=timeout_sec,
        grace_sec=_COMMAND_TIMEOUT_SECONDS,
        purpose="the platform consumer compatibility check",
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
    result: Dict[str, Any],
    *,
    candidate_sha: str,
    consumer_sha: str,
    run_id: str,
    exact_pair: bool = True,
) -> Tuple[int, str, str]:
    """Return code, diagnostic and proven revision (empty on refusal)."""
    where = str(result.get("html_url") or "").strip() or f"run {run_id}"
    state = str(result.get("state") or "").strip()
    proven = str(result.get("head_sha") or "").strip()
    if state == "timeout":
        return (
            UNAVAILABLE,
            (
                f"consumer compatibility unproven: {where} had not concluded "
                "within the wait budget. The candidate stays unpublished until it "
                "does; re-running this gate rejoins the same consumer run."
            ),
            "",
        )
    if state != "success":
        from runtime.api.tools.consumer_failure_attribution import (
            producer_failure_context,
        )

        conclusion = str(result.get("conclusion") or state or "unknown")
        against = proven or consumer_sha or "an unnamed revision"
        return (
            UNPROVEN,
            (
                f"the hosted consumer refused this candidate: product "
                f"{candidate_sha} against consumer {against} concluded "
                f"{conclusion} — {where}. {producer_failure_context(candidate_sha)} "
                "Fix the producer regression or land the paired consumer adaptation, "
                f"which is a linked companion item in the {CONSUMER_PROJECT} "
                "project; an instruction that excludes redesigning the consumer "
                "never waives adapting it."
            ),
            "",
        )
    if not _FULL_SHA.match(proven):
        return (
            UNPROVEN,
            (
                f"consumer evidence names no revision it proved: {where} "
                "concluded success without a readable head commit, so it cannot "
                f"be attributed to product {candidate_sha}. That is unproven, "
                "not proven; re-run the gate."
            ),
            "",
        )
    if exact_pair and proven.lower() != consumer_sha.lower():
        return (
            UNPROVEN,
            (
                f"stale pair: {CONSUMER_TRUNK_REF} moved past the bound commit "
                f"— {where} proved {proven}, not {consumer_sha}, for product "
                f"{candidate_sha}. This intent stays unproven; start a new "
                "deployment run to bind a fresh consumer commit rather than "
                "retrying this pair."
            ),
            "",
        )
    return (
        0,
        (
            f"hosted consumer builds against this candidate: product "
            f"{candidate_sha} with consumer {proven} — {where}"
        ),
        proven,
    )


def prove(
    candidate_sha: str, consumer_sha: str, *, timeout_sec: int
) -> Tuple[int, str, str]:
    """Bind, dispatch, wait, classify — code, narrative, proven revision."""
    unavailable = bind_consumer_authority()
    if unavailable:
        return UNAVAILABLE, f"consumer compatibility unproven: {unavailable}", ""
    return prove_pair(candidate_sha, consumer_sha, timeout_sec=timeout_sec)


def prove_pair(
    candidate_sha: str, consumer_sha: str, *, timeout_sec: int
) -> Tuple[int, str, str]:
    """Dispatch or join the exact pair, wait and classify under bound authority."""
    run_id, dispatch_error = dispatch(candidate_sha, consumer_sha)
    if dispatch_error:
        return UNAVAILABLE, f"consumer compatibility unproven: {dispatch_error}", ""
    print(f"consumer check run: {CONSUMER_REPO} run {run_id}", flush=True)
    result, unreadable = await_verdict(run_id, timeout_sec=timeout_sec)
    if unreadable:
        return UNAVAILABLE, f"consumer compatibility unproven: {unreadable}", ""
    return classify(
        result,
        candidate_sha=candidate_sha,
        consumer_sha=consumer_sha,
        run_id=run_id,
    )


def _write_output(key: str, value: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        return
    with open(output, "a", encoding="utf-8") as handle:
        handle.write(f"{key}={value}\n")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="require_platform_consumer_compatibility",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--candidate-sha", default="")
    parser.add_argument("--consumer-sha", default="")
    parser.add_argument("--timeout", type=int, default=1800, dest="timeout_sec")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    candidate = args.candidate_sha.strip().lower()
    consumer = args.consumer_sha.strip().lower()
    if not _FULL_SHA.match(candidate):
        print(
            "consumer compatibility unproven: --candidate-sha must be a full "
            f"40-hex commit, got {args.candidate_sha!r}. A short sha is "
            "resolved by the consumer against whatever it names there.",
            file=sys.stderr,
        )
        return UNAVAILABLE
    if not _FULL_SHA.match(consumer):
        print(
            "consumer compatibility unproven: --consumer-sha must be a full "
            f"40-hex commit, got {args.consumer_sha!r}. The caller binds the "
            "exact consumer commit; this gate never resolves it.",
            file=sys.stderr,
        )
        return UNAVAILABLE

    code, narrative, proven_revision = prove(
        candidate,
        consumer,
        timeout_sec=args.timeout_sec,
    )
    if code:
        print(narrative, file=sys.stderr)
        return code
    # Named so promotion can refuse to ship against a different revision.
    _write_output("proven_consumer_sha", proven_revision)
    print(narrative)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
