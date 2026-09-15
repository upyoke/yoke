"""Refuse to publish a release the hosted consumer has not been built against.

A producer-only green run proves the producer and nothing else. Before the
release train allocates its annotated tag, the consumer's own
release-pin check builds the real host against this exact candidate.

Usage::

    python3 -m runtime.api.tools.require_platform_consumer_compatibility \\
        --candidate-sha <40-hex> --consumer-sha <40-hex> [--timeout SEC]

Both shas must be full 40-hex commits. The exact pair is that candidate and
that consumer commit; simultaneous callers proving the identical pair share
one ``github-actions trigger --request-id``, so they join one run instead of
dispatching two. A different consumer commit is a different pair and never
adopts an earlier proof — the caller is responsible for binding the exact
consumer commit before invoking this gate (the deployment pipeline's own
driver resolves it, recovering an already-bound value before ever resolving
fresh, so a retry can never drift). Floating ``main`` is never the identity,
and missing or mismatched evidence is unproven.

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
import uuid
from typing import Any, Dict, Optional, Sequence, Tuple

from yoke_contracts.api_urls import HOSTED_PROD_API_URL
from yoke_contracts.github_workflow_dispatch import (
    WORKFLOW_DISPATCH_CORRELATION_INPUT,
)

#: The consumer that builds against this repo's universe bundle, and the
#: check it already requires on its own pull requests; a candidate commit
#: redirects what it builds against. Agreed with the consumer side.
CONSUMER_REPO = "upyoke/platform"
CONSUMER_PROJECT = "platform"
CONSUMER_CHECK_WORKFLOW = "platform-release-pin-check.yml"
#: The one supported named ref every dispatch targets (a bare commit 422s).
CONSUMER_TRUNK_REF = "main"
CANDIDATE_INPUT = "product_ref"

#: CI-only token for this helper's connection bootstrap, not local dispatch.
CONSUMER_TOKEN_ENV = "YOKE_PLATFORM_RELEASE_API_TOKEN"

#: A connection of its own, so binding it never disturbs whichever
#: authority the caller had already selected for its other steps.
CONSUMER_CONNECTION = "platform-consumer-check"

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_COMMAND_TIMEOUT_SECONDS = 300


def pair_request_id(candidate_sha: str, consumer_sha: str) -> str:
    """Shared key for this exact (candidate, consumer) pair.

    A different consumer commit changes this key, so a caller can never
    adopt a proof taken against a different pair.
    """
    return (
        f"consumer-compat:{candidate_sha}:{consumer_sha}:"
        f"{CONSUMER_CHECK_WORKFLOW}"
    )


def fresh_request_id(candidate_sha: str) -> str:
    """One-shot key for a non-exact-pair dispatch (the advisory check).

    Minted fresh on every call, so a caller with no bound consumer commit
    to key on (a branch name is not an identity) can never permanently
    reuse a proof taken against an earlier, possibly stale, consumer trunk.
    """
    return (
        f"consumer-compat:{candidate_sha}:{uuid.uuid4().hex}:"
        f"{CONSUMER_CHECK_WORKFLOW}"
    )

#: The consumer refused the candidate, or its evidence does not name it.
UNPROVEN = 1
#: No verdict could be obtained at all.
UNAVAILABLE = 2


def is_full_commit_sha(value: str) -> bool:
    """Whether *value* is a full 40-hex commit the consumer cannot re-resolve."""
    return bool(_FULL_SHA.match(str(value or "").strip().lower()))


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
    candidate_sha: str, consumer_sha: str, *, exact_pair: bool = True,
) -> Tuple[str, str]:
    """Dispatch or recover the consumer run onto the supported named ref.

    ``exact_pair`` selects the request-id shape: the publication gate shares
    one durable key per (candidate, consumer) pair, so simultaneous callers
    proving the identical pair join one run. The advisory check has no
    bound commit to key on — a branch name is not an identity — so it mints
    a fresh key every call, trading reuse for never adopting a stale proof.
    """
    request_id = (
        pair_request_id(candidate_sha, consumer_sha) if exact_pair
        else fresh_request_id(candidate_sha)
    )
    code, stdout, stderr = _yoke(
        [
            "github-actions",
            "trigger",
            CONSUMER_REPO,
            CONSUMER_CHECK_WORKFLOW,
            "--ref",
            CONSUMER_TRUNK_REF,
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
        timeout=timeout_sec + _COMMAND_TIMEOUT_SECONDS,
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
    result: Dict[str, Any], *, candidate_sha: str, consumer_sha: str, run_id: str,
    exact_pair: bool = True,
) -> Tuple[int, str, str]:
    """Exit code, narrative, and the consumer revision actually proven.

    ``exact_pair`` enforces that the run's own evidence names exactly
    ``consumer_sha`` — the publication gate's contract. A caller with no way
    to bind the exact consumer commit ahead of dispatch (the advisory check,
    which has no durable driver authority to resolve one) passes a branch
    name for ``consumer_sha`` and ``exact_pair=False``, trusting whatever
    the dispatched run reports instead of demanding a match.

    The revision is empty on every non-zero code: nothing was proven, so
    there is nothing promotion may bind itself to.
    """
    where = str(result.get("html_url") or "").strip() or f"run {run_id}"
    state = str(result.get("state") or "").strip()
    proven = str(result.get("head_sha") or "").strip()
    if state == "timeout":
        return UNAVAILABLE, (
            f"consumer compatibility unproven: {where} had not concluded "
            "within the wait budget. The candidate stays unpublished until it "
            "does; re-running this gate rejoins the same consumer run."
        ), ""
    if state != "success":
        conclusion = str(result.get("conclusion") or state or "unknown")
        against = proven or consumer_sha or "an unnamed revision"
        return UNPROVEN, (
            f"the hosted consumer refused this candidate: product "
            f"{candidate_sha} against consumer {against} concluded "
            f"{conclusion} — {where}. Land the paired consumer adaptation, "
            f"which is a linked companion item in the {CONSUMER_PROJECT} "
            "project; an instruction that excludes redesigning the consumer "
            "never waives adapting it."
        ), ""
    if not _FULL_SHA.match(proven):
        return UNPROVEN, (
            f"consumer evidence names no revision it proved: {where} "
            "concluded success without a readable head commit, so it cannot "
            f"be attributed to product {candidate_sha}. That is unproven, "
            "not proven; re-run the gate."
        ), ""
    if exact_pair and proven.lower() != consumer_sha.lower():
        return UNPROVEN, (
            f"stale pair: {CONSUMER_TRUNK_REF} moved past the bound commit "
            f"— {where} proved {proven}, not {consumer_sha}, for product "
            f"{candidate_sha}. This intent stays unproven; start a new "
            "deployment run to bind a fresh consumer commit rather than "
            "retrying this pair."
        ), ""
    return 0, (
        f"hosted consumer builds against this candidate: product "
        f"{candidate_sha} with consumer {proven} — {where}"
    ), proven


def prove(
    candidate_sha: str, consumer_sha: str, *, timeout_sec: int, exact_pair: bool = True,
) -> Tuple[int, str, str]:
    """Bind, dispatch, wait, classify — code, narrative, proven revision."""
    unavailable = bind_consumer_authority()
    if unavailable:
        return UNAVAILABLE, f"consumer compatibility unproven: {unavailable}", ""
    run_id, dispatch_error = dispatch(candidate_sha, consumer_sha, exact_pair=exact_pair)
    if dispatch_error:
        return UNAVAILABLE, f"consumer compatibility unproven: {dispatch_error}", ""
    print(f"consumer check run: {CONSUMER_REPO} run {run_id}", flush=True)
    result, unreadable = await_verdict(run_id, timeout_sec=timeout_sec)
    if unreadable:
        return UNAVAILABLE, f"consumer compatibility unproven: {unreadable}", ""
    return classify(
        result, candidate_sha=candidate_sha, consumer_sha=consumer_sha, run_id=run_id,
        exact_pair=exact_pair,
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
        candidate, consumer, timeout_sec=args.timeout_sec,
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
