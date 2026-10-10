"""Keep the proven consumer revision current with the consumer's trunk.

The pre-tag proof builds the hosted consumer against the release candidate at
one exact consumer commit, and promotion refuses to ship a consumer trunk that
carries changes beyond that commit. The tag, the wheel and the server-image
factories run between the two, so the trunk can move while nothing is
watching it — and then promotion refuses a pair that was never wrong, only
late.

So right before promotion is dispatched, the consumer trunk is read again:

* unchanged — the proven commit is handed on as it is;
* moved forward (the head descends from the proven commit) — the candidate is
  proven again against the new head, and that head is handed on, so every
  consumer commit that ships has been built against the exact candidate;
* rewritten or moved back — refused by name: nothing proves what promotion
  would ship, and only a new deployment run binds a commit afresh.

A control plane that does not yet serve the trunk read leaves the proven
commit as it was, with a warning; promotion's own refusal stays the backstop.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Tuple

from runtime.api.tools.require_platform_consumer_compatibility import (
    CONSUMER_PROJECT,
    CONSUMER_TRUNK_REF,
    UNAVAILABLE,
    UNPROVEN,
    _COMMAND_TIMEOUT_SECONDS,
    _detail,
    _yoke,
    bind_consumer_authority,
    prove,
)

#: The trunk moved again while the candidate was being proven against it.
MOVED_AGAIN = 3

#: Codes a control plane answers with when it predates the trunk read.
_UNSERVED_CODES = frozenset({"function_version_skew", "function_not_registered"})


def read_trunk(since: str) -> Tuple[Dict[str, Any], str, bool]:
    """The trunk head and its relation to ``since``.

    Returns ``(result, error, unserved)``; ``unserved`` is true only when the
    control plane does not serve the read at all.
    """
    code, stdout, stderr = _yoke(
        [
            "github",
            "branch",
            "head",
            CONSUMER_TRUNK_REF,
            "--since",
            since,
            "--project",
            CONSUMER_PROJECT,
            "--json",
        ],
        timeout=_COMMAND_TIMEOUT_SECONDS,
    )
    try:
        payload = json.loads(stdout)
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        return {}, f"consumer trunk read unreadable: {_detail(stdout, stderr)}", False
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    if code != 0 or not payload.get("success"):
        unserved = str(error.get("code") or "") in _UNSERVED_CODES
        return {}, f"consumer trunk read refused: {_detail(stdout, stderr)}", unserved
    result = payload.get("result")
    if not isinstance(result, dict) or not result.get("head_sha"):
        return (
            {},
            f"consumer trunk read named no head: {_detail(stdout, stderr)}",
            False,
        )
    return result, "", False


def follow(
    candidate_sha: str,
    proven_sha: str,
    *,
    timeout_sec: int,
) -> Tuple[int, str, str]:
    """Code, narrative, and the consumer revision promotion should bind to."""
    unavailable = bind_consumer_authority()
    if unavailable:
        return UNAVAILABLE, f"consumer trunk unread: {unavailable}", ""
    trunk, unreadable, unserved = read_trunk(proven_sha)
    if unserved:
        return (
            0,
            (
                f"::warning title=consumer_trunk_unread::{unreadable}. The control "
                "plane predates the trunk read, so promotion binds to the proven "
                f"{proven_sha} unchanged; its own refusal names a moved trunk."
            ),
            proven_sha,
        )
    if unreadable:
        return (
            UNAVAILABLE,
            (
                f"{unreadable}. Re-run the bridge once the control plane answers; "
                "nothing has been dispatched to the consumer yet."
            ),
            "",
        )
    head = str(trunk.get("head_sha") or "").lower()
    relation = str(trunk.get("relation") or "")
    if relation == "identical":
        return (
            0,
            (f"consumer {CONSUMER_TRUNK_REF} is still the proven {proven_sha}"),
            proven_sha,
        )
    if relation != "descendant":
        return (
            UNPROVEN,
            (
                f"consumer {CONSUMER_TRUNK_REF} is now {head}, which does not "
                f"descend from the proven {proven_sha} ({relation or 'no relation'})"
                ": the trunk was rewritten or moved back, so nothing proves what "
                "promotion would ship. Leave this run failed and start a new "
                "deployment run, which binds the current trunk."
            ),
            "",
        )
    print(
        f"consumer {CONSUMER_TRUNK_REF} moved from the proven {proven_sha} to "
        f"its descendant {head}; proving candidate {candidate_sha} against it",
        flush=True,
    )
    code, narrative, proven = prove(candidate_sha, head, timeout_sec=timeout_sec)
    if code == 0:
        return 0, narrative, proven
    again, _, _ = read_trunk(head)
    if again.get("relation") == "descendant":
        return (
            MOVED_AGAIN,
            (
                f"{narrative} — and {CONSUMER_TRUNK_REF} moved on to "
                f"{again.get('head_sha')} meanwhile"
            ),
            "",
        )
    return code, narrative, ""


__all__ = ["MOVED_AGAIN", "follow", "read_trunk"]
