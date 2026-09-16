"""Project-scoped item reference formatting — pure, client-tier.

A public item ref is ``<public_item_prefix>-<project_sequence>`` (for
example, ``YOK-N``). Hosted in yoke_contracts so the board render (and any client)
can format refs without ``yoke_core``; ``yoke_core.domain.project_identity``
re-exports these for its existing callers.
"""

from __future__ import annotations

import re
from typing import Any, Optional, Tuple

DEFAULT_PUBLIC_ITEM_PREFIX = "YOK"

_PUBLIC_REF_RE = re.compile(r"^(?P<prefix>[A-Za-z][A-Za-z0-9]*)-(?P<seq>\d+)$")
_BARE_SEQUENCE_RE = re.compile(r"^\d+$")


def format_item_ref(
    project_slug: Any,
    public_item_prefix: Any,
    project_sequence: Any,
    *,
    qualify: bool = False,
) -> str:
    """Format one project-scoped reference from its own two identity parts.

    A sequence this cannot read is :func:`unresolved_item_ref`, never a
    number borrowed from elsewhere: ``items.id`` and ``project_sequence``
    are independent counters, so substituting one for the other prints a
    reference that names a different item.
    """
    del project_slug, qualify
    prefix = str(public_item_prefix or DEFAULT_PUBLIC_ITEM_PREFIX)
    try:
        sequence = int(project_sequence)
    except (TypeError, ValueError):
        return unresolved_item_ref()
    return f"{prefix}-{sequence}"


def unresolved_item_ref(requested: Any = None, *, consulted: bool = True) -> str:
    """Return the phrase that stands in for an unresolvable reference.

    Human-visible text names an item by its public reference or says plainly
    that it could not resolve one. It never carries ``items.id``: the storage
    key reads as a reference to whoever sees it, and the two counters are
    independent, so the number shown would name a different item. The
    internal key belongs to structured diagnostics — event and telemetry
    payloads carry it as their own bare integer field — and stays out of
    every rendered phrase.

    ``requested`` is the token the caller was already handed, echoed only
    when it is a full ``PREFIX-N`` reference that simply did not resolve:
    that much is useful to the reader and cannot be an internal key. A bare
    number is not a reference — it names a sequence with no project, which is
    exactly the shape ``items.id`` has — so it renders the plain label.

    ``consulted`` separates the two empty outcomes: a read that found no
    identity row, and a caller that had no connection to read with. The
    bracketed shape keeps the phrase from being pasted back as a reference.
    """
    reason = "no project identity row" if consulted else "no control-plane read"
    prefix, sequence = parse_public_item_ref(requested)
    if prefix is None or sequence is None:
        return f"<unresolved item ref: {reason}>"
    return f"<unresolved item ref: {reason}, requested {prefix}-{sequence}>"


def parse_public_item_ref(text: Any) -> Tuple[Optional[str], Optional[int]]:
    """Split a reference into its prefix and sequence — the read direction of
    :func:`format_item_ref`.

    Returns ``(prefix, sequence)`` for the full ``PREFIX-N`` form with the
    prefix upper-cased, and ``(None, sequence)`` for a bare ``N``, which names
    a sequence but no project and so only identifies an item once the caller
    supplies one. Free text that is neither shape yields ``(None, None)``.
    """
    candidate = str(text or "").strip()
    if _BARE_SEQUENCE_RE.match(candidate):
        return None, int(candidate)
    match = _PUBLIC_REF_RE.match(candidate)
    if match is None:
        return None, None
    return match.group("prefix").upper(), int(match.group("seq"))
