"""The minimum artifact version safe to serve against an applied entry.

A migration that removes a surface splits the world in two: builds that were
written after the removal, which never read it, and builds written before,
which do. Applying such an entry is safe. *Serving an older build against a
database that already applied it* is not, and nothing about the ledger says
so — membership is by name, so an older wheel whose history simply does not
contain the newer entry computes an empty pending set and reports itself
current. The question "has this database had something applied that my code
cannot survive?" is unasked rather than answered wrongly.

This module is the vocabulary for asking it. An entry that removes a surface
declares the oldest artifact version that may serve against it; the applier
refuses to run ahead of its own declaration; and the declaration is copied
into the ledger row at apply time, because a build old enough to be in danger
does not ship the entry module and could not read a declaration that lives
only there.

Deliberately project-agnostic. Any project declaring a migration model gets
this contract, so nothing here names Yoke, its wheel, or its history — the
caller supplies the running version, and what that version *is* belongs to
the project's declared model.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from packaging.version import InvalidVersion, Version

#: Module-level constant an entry sets to declare its floor. The name is the
#: contract; there is no registration step and no side table, so the
#: declaration cannot drift from the entry that needs it.
DECLARATION_ATTRIBUTE = "MINIMUM_SERVING_VERSION"

#: DDL that removes a surface a running build might still read. Matched
#: against the entry's own source text rather than its behavior, because the
#: authoring check has to answer before anything is executed. Over-matching
#: is the safe direction: a false positive costs one declaration, while a
#: false negative is the outage this exists to prevent.
_SURFACE_REMOVAL_SQL = re.compile(
    r"\bDROP\s+(COLUMN|TABLE)\b",
    re.IGNORECASE,
)


class ServingVersionError(Exception):
    """An entry's serving-version contract is unsatisfiable or unsatisfied."""


def removes_a_surface(source: str) -> bool:
    """Whether *source* contains DDL that removes a surface.

    Source text, not a live connection: an entry has to satisfy the authoring
    check before it is ever applied anywhere.
    """
    return _SURFACE_REMOVAL_SQL.search(source) is not None


def declared_minimum(module: Any) -> Optional[str]:
    """Return an entry module's declared floor, or ``None`` when absent."""
    declared = getattr(module, DECLARATION_ATTRIBUTE, None)
    if declared is None:
        return None
    text = str(declared).strip()
    if not text:
        return None
    try:
        Version(text)
    except InvalidVersion as exc:
        raise ServingVersionError(
            f"{DECLARATION_ATTRIBUTE} is not a valid version: {declared!r}"
        ) from exc
    return text


def require_declaration(entry_name: str, source: str, module: Any) -> Optional[str]:
    """Return the declared floor, refusing a surface removal that lacks one.

    This is the authoring gate. A forgettable declaration reproduces the very
    class of failure the declaration exists to prevent, so the entry that
    removes something is required to say what it breaks — at authoring time,
    where the author is present to answer.
    """
    declared = declared_minimum(module)
    if declared is not None:
        return declared
    if not removes_a_surface(source):
        return None
    raise ServingVersionError(
        f"migration entry {entry_name!r} removes a surface (DROP COLUMN/TABLE) "
        f"but declares no {DECLARATION_ATTRIBUTE}. Set it to the oldest "
        "artifact version that may serve against this database once the entry "
        "has been applied — that is the version in which nothing reads the "
        "removed surface any more."
    )


def version_is_unresolved(running_version: str) -> bool:
    """Whether *running_version* carries no usable release identity.

    A source checkout is the case that matters. Its advertised version names
    the last tag, not the code, so a tree that is dozens of commits *ahead*
    of a release compares as that release — and an entry authored in that
    very tree would refuse to serve on the machine that wrote it, and in
    every test run. An unresolved version is a distinct answer from an old
    one, and the caller decides what to do about it.
    """
    return not running_version.strip()


def satisfies_minimum(running_version: str, declared_minimum_version: str) -> bool:
    """Whether *running_version* is new enough to serve against the entry.

    Comparison is PEP 440 through ``packaging``, which orders local segments
    (``0.1.1+launch.169`` before ``0.1.1+launch.180``) correctly. Hand-rolling
    that ordering is how a comparator ends up disagreeing with the resolver
    every other part of the system uses.
    """
    try:
        return Version(running_version) >= Version(declared_minimum_version)
    except InvalidVersion as exc:
        raise ServingVersionError(
            f"cannot compare running version {running_version!r} with declared "
            f"minimum {declared_minimum_version!r}: {exc}"
        ) from exc


def refuse_if_behind(
    entry_name: str,
    running_version: str,
    declared_minimum_version: Optional[str],
) -> None:
    """Raise when the running artifact predates an entry's declared floor.

    Used by the applier, which is the cheapest place to catch an authoring
    mistake: an entry whose floor is newer than the build running it can only
    mean the declaration and the code disagree, and catching that before the
    DDL lands costs nothing.

    An unresolved running version passes. Refusing there would brick every
    source checkout and every test, and a source tree is by construction at
    or ahead of the entry it carries.
    """
    if declared_minimum_version is None:
        return
    if version_is_unresolved(running_version):
        return
    if satisfies_minimum(running_version, declared_minimum_version):
        return
    raise ServingVersionError(
        f"migration entry {entry_name!r} declares a minimum serving version of "
        f"{declared_minimum_version}, but this build advertises "
        f"{running_version}. Applying it here would leave this database unable "
        "to be served by the code that just applied it. Deploy the newer "
        "artifact first, then let its boot apply this entry."
    )


__all__ = [
    "DECLARATION_ATTRIBUTE",
    "ServingVersionError",
    "declared_minimum",
    "refuse_if_behind",
    "removes_a_surface",
    "require_declaration",
    "satisfies_minimum",
    "version_is_unresolved",
]
