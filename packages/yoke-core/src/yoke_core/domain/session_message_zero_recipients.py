"""The refusal a selector that reached nobody should teach.

Resolving to zero sessions is the safe outcome of a bad address, and it
was reported as bare fact: "recipient selector resolved to zero sessions".
A sender who had guessed at a session id read that as "not running" and
guessed again. The dangerous case is the one that does not refuse — a
session id is exact, so a fragment or a padded value usually matches
nothing, but thousands of sessions share leading characters and a lucky
guess resolves to a real session that is the wrong one.

So the refusal names which anchor found nobody and points at the address
that cannot be guessed wrong: a live item claim has exactly one holder.
"""

from __future__ import annotations

from yoke_contracts.session_control.models import RecipientSelector
from yoke_core.domain.session_message_types import (
    ResolvedRecipient,
    SessionMessageError,
)


ZERO_RECIPIENTS_CODE = "zero_recipients"


def _listed(values: list[str]) -> str:
    return ", ".join(values)


def zero_recipients_detail(selector: RecipientSelector) -> str:
    """Name the anchor that resolved to nobody, plus the way forward."""
    if selector.session_ids:
        return (
            "no session matches the session id(s) "
            f"{_listed(selector.session_ids)}. A session id is matched whole "
            "and exactly; a shortened, padded, or hand-assembled one either "
            "misses or lands on a different session that shares its leading "
            "characters. Address the worker by its work instead — "
            "`yoke say --item PREFIX-N --stdin` reaches the one holder of a "
            "live claim — or take a whole id from `yoke sessions list "
            "--liveness active`."
        )
    if selector.item_refs:
        return (
            f"no session holds a live work claim on {_listed(selector.item_refs)}, "
            "so the item addresses nobody right now. Confirm the holder with "
            "`yoke claims work holder-get PREFIX-N`; an unclaimed item has no "
            "worker to reach, and a just-released one is between segments."
        )
    if selector.epic_tasks:
        return (
            f"no session holds a live claim on epic task(s) "
            f"{_listed(selector.epic_tasks)}. Confirm the task is staffed "
            "before addressing it."
        )
    if selector.process_keys:
        return f"no session holds the process key(s) {_listed(selector.process_keys)}."
    if selector.projects or selector.universe:
        return (
            "the roster audience resolved to zero sessions. Recipient filters "
            "intersect the anchor, and --project and --universe resolve "
            "against active sessions unless --liveness widens them; check "
            "`yoke sessions list --liveness active` and drop a filter."
        )
    return (
        "the recipient selector resolved to zero sessions. Choose an anchor: "
        "--item PREFIX-N addresses the holder of a live claim, and --session "
        "takes a whole id from `yoke sessions list --liveness active`."
    )


def require_recipients(
    recipients: list[ResolvedRecipient],
    selector: RecipientSelector,
) -> None:
    """Refuse an empty resolution, naming the anchor and the way forward."""
    if not recipients:
        raise SessionMessageError(
            ZERO_RECIPIENTS_CODE, zero_recipients_detail(selector)
        )


__all__ = [
    "ZERO_RECIPIENTS_CODE",
    "require_recipients",
    "zero_recipients_detail",
]
