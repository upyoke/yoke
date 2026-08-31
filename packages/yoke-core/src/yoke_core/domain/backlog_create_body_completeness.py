"""Warn when a created item carries nothing a later session could work from.

An item whose body is just its own title reads as filed work and gives the
session that picks it up no problem statement, no plan, and no acceptance
criteria. The create still succeeds — the operator may be filing a
placeholder deliberately — but it says so, and names the one command that
fills the gap.
"""

from __future__ import annotations

import sys
from typing import Optional, TextIO


def warn_when_body_is_empty(
    *,
    public_ref: str,
    title: str,
    body: str,
    instruction: str,
    out: Optional[TextIO] = None,
) -> bool:
    """Print the empty-body warning; return whether it fired."""
    out = out if out is not None else sys.stderr
    if instruction or len(body) > len(f"# {title}") + 4:
        return False
    print("", file=out)
    print(f"WARNING: {public_ref} created with no body content.", file=out)
    print(
        "Cold-start sessions need full context: problem, fix plan, "
        "acceptance criteria.",
        file=out,
    )
    print(
        "Use: printf '%s' \"$content\" | yoke items structured-field replace "
        f"{public_ref} --field spec --stdin",
        file=out,
    )
    print("", file=out)
    return True


__all__ = ["warn_when_body_is_empty"]
