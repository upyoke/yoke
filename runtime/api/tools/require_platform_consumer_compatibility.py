"""Refuse to publish a release the hosted consumer has not been built against.

A producer-only green run proves the producer and nothing else. Before the
release train allocates its annotated tag, the consumer's own
release-pin check builds the real host against this exact candidate.

Usage::

    python3 -m runtime.api.tools.require_platform_consumer_compatibility \\
        --candidate-sha <40-hex> [--timeout SEC]

*candidate-sha* must be a full 40-hex commit. This gate always calls the
currently-serving control plane, because it runs before the release it is
gating has published anything — so it never depends on a server-side field
this same release introduces; binding a value like that would make the
release unable to ship until after it had already shipped. Trunk is
resolved the same way the dispatched run itself resolves it: this gate
dispatches onto the consumer's trunk branch and lets GitHub name the exact
commit at that moment, then reads it back from the run's own evidence. That
also fixes staleness structurally rather than by convention — a stale
resolve-then-dispatch race is impossible when there is nothing to resolve
ahead of dispatch.

Simultaneous callers (a stage and a prod release proving the same product
commit) share one ``github-actions trigger --request-id`` keyed on the
candidate, so they join one run instead of dispatching two; a failed or
cancelled run advances a new attempt on the same key. Reproving the same
candidate later reuses that same run once it is live or already proved —
idempotent same-candidate retries are intentional, since a given candidate
commit is immutable once merged. Missing or refused evidence is unproven.

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

from yoke_contracts.api_urls import HOSTED_PROD_API_URL
from yoke_contracts.github_workflow_dispatch import (
    WORKFLOW_DISPATCH_CORRELATION_INPUT,
)

#: The consumer that builds against this repo's universe bundle, and the
#: check it already requires on its own pull requests. Passing a candidate
#: commit redirects what that check builds against; absent one it is the
#: ordinary pinned-wheel check. Agreed with the consumer side; changing
#: either name is a change to both repos.
CONSUMER_REPO = "upyoke/platform"
CONSUMER_PROJECT = "platform"
CONSUMER_CHECK_WORKFLOW = "platform-release-pin-check.yml"
CONSUMER_TRUNK_REF = "main"
CANDIDATE_INPUT = "product_ref"

#: Scoped API token for the consumer project's GitHub binding.
CONSUMER_TOKEN_ENV = "YOKE_PLATFORM_RELEASE_API_TOKEN"

#: A connection of its own, so binding it never disturbs whichever
#: authority the caller had already selected for its other steps.
CONSUMER_CONNECTION = "platform-consumer-check"

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_COMMAND_TIMEOUT_SECONDS = 300


def candidate_request_id(candidate_sha: str) -> str:
    """The idempotency key simultaneous stage/prod callers share.

    Keyed on the candidate alone, not a pre-resolved consumer commit: the
    consumer commit is never known before dispatch (see module docstring),
    and a candidate commit is immutable, so reusing this key for retries of
    the same candidate is the intended, safe behavior.
    """
    return f"consumer-compat:{candidate_sha}:{CONSUMER_CHECK_WORKFLOW}"

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
            f"no scoped consumer credential in {CONSUMER_TOKEN_ENV}; the "
            "release train provides it, and nothing can reach the consumer's "
            "check without it."
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


def dispatch(candidate_sha: str) -> Tuple[str, str]:
    """Dispatch or recover the consumer run for this exact candidate.

    Dispatches onto ``CONSUMER_TRUNK_REF`` by name rather than a pre-resolved
    commit, so GitHub — not this gate — resolves the exact trunk commit at
    the moment of dispatch. See the module docstring for why that also
    avoids a rollout dependency on this repo's own not-yet-served changes.
    """
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
            candidate_request_id(candidate_sha),
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
    result: Dict[str, Any], *, candidate_sha: str, run_id: str,
) -> Tuple[int, str, str]:
    """Exit code, narrative, and the consumer revision actually proven."""
    where = str(result.get("html_url") or "").strip() or f"run {run_id}"
    state = str(result.get("state") or "").strip()
    consumer_sha = str(result.get("head_sha") or "").strip()
    if state == "timeout":
        return UNAVAILABLE, (
            f"consumer compatibility unproven: {where} had not concluded "
            "within the wait budget. The candidate stays unpublished until it "
            "does; re-running this gate rejoins the same consumer run."
        ), ""
    if state != "success":
        conclusion = str(result.get("conclusion") or state or "unknown")
        against = consumer_sha or "an unnamed revision"
        return UNPROVEN, (
            f"the hosted consumer refused this candidate: product "
            f"{candidate_sha} against consumer {against} concluded "
            f"{conclusion} — {where}. Land the paired consumer adaptation, "
            f"which is a linked companion item in the {CONSUMER_PROJECT} "
            "project; an instruction that excludes redesigning the consumer "
            "never waives adapting it."
        ), ""
    if not _FULL_SHA.match(consumer_sha):
        return UNPROVEN, (
            f"consumer evidence names no revision it proved: {where} "
            "concluded success without a readable head commit, so it cannot "
            f"be attributed to product {candidate_sha}. That is unproven, "
            "not proven; re-run the gate."
        ), ""
    return 0, (
        f"hosted consumer builds against this candidate: product "
        f"{candidate_sha} with consumer {consumer_sha} — {where}"
    ), consumer_sha


def prove(candidate_sha: str, *, timeout_sec: int) -> Tuple[int, str, str]:
    """Bind, dispatch, wait, classify."""
    unavailable = bind_consumer_authority()
    if unavailable:
        return UNAVAILABLE, f"consumer compatibility unproven: {unavailable}", ""
    run_id, dispatch_error = dispatch(candidate_sha)
    if dispatch_error:
        return UNAVAILABLE, f"consumer compatibility unproven: {dispatch_error}", ""
    print(f"consumer check run: {CONSUMER_REPO} run {run_id}", flush=True)
    result, unreadable = await_verdict(run_id, timeout_sec=timeout_sec)
    if unreadable:
        return UNAVAILABLE, f"consumer compatibility unproven: {unreadable}", ""
    return classify(result, candidate_sha=candidate_sha, run_id=run_id)


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
    parser.add_argument("--timeout", type=int, default=1800, dest="timeout_sec")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    candidate = args.candidate_sha.strip().lower()
    if not _FULL_SHA.match(candidate):
        print(
            "consumer compatibility unproven: --candidate-sha must be a full "
            f"40-hex commit, got {args.candidate_sha!r}. A short sha is "
            "resolved by the consumer against whatever it names there.",
            file=sys.stderr,
        )
        return UNAVAILABLE

    code, narrative, proven_revision = prove(
        candidate, timeout_sec=args.timeout_sec,
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
