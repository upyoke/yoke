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
refuses to run ahead of its own declaration; and the declaration is resolved
and copied into the ledger row at apply time, because a build old enough to be
in danger does not ship the entry module and could not read a declaration that
lives only there.

A newly authored entry cannot name that version, because it is a release that
does not exist yet — every version its author could write was cut before the
entry and therefore cannot serve what it produces. So the vocabulary includes
a sentinel for exactly that, and refuses a literal on an entry no release
carries.

Deliberately project-agnostic. Any project declaring a migration model gets
this contract, so nothing here names Yoke, its wheel, or its history — the
caller supplies the running version, and what that version *is* belongs to
the project's declared model.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from packaging.version import InvalidVersion, Version

#: Module-level constant an entry sets to declare its floor. The name is the
#: contract; there is no registration step and no side table, so the
#: declaration cannot drift from the entry that needs it.
DECLARATION_ATTRIBUTE = "MINIMUM_SERVING_VERSION"

#: The floor a not-yet-released entry declares. A new destructive entry can
#: only be served by a release that does not exist yet, so there is no literal
#: version an author could write that would be true: every version they can
#: name was cut before the entry existed and therefore cannot read the schema
#: it produces. Writing the newest existing release is the mistake this
#: sentinel removes — it once left a fleet-wide floor naming precisely the
#: build that could not serve the change. The sentinel resolves at apply time
#: to the artifact doing the applying, which by construction contains the
#: entry, so the ledger row still records a real, comparable version.
NEXT_RELEASE = "next-release"

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
    """Return an entry module's declared floor, or ``None`` when absent.

    The value is either a PEP 440 version or :data:`NEXT_RELEASE`; the
    sentinel is returned verbatim, because it names a release that does not
    exist yet and so has nothing to parse.
    """
    declared = getattr(module, DECLARATION_ATTRIBUTE, None)
    if declared is None:
        return None
    text = str(declared).strip()
    if not text:
        return None
    if text == NEXT_RELEASE:
        return text
    try:
        Version(text)
    except InvalidVersion as exc:
        raise ServingVersionError(
            f"{DECLARATION_ATTRIBUTE} is not a valid version: {declared!r}"
        ) from exc
    return text


def recorded_floor(module: Any, *, running_version: str) -> Optional[str]:
    """The floor to write on this entry's ledger row.

    A literal is recorded as authored. :data:`NEXT_RELEASE` resolves to
    *running_version*, because the artifact applying an entry is by
    construction one that contains it — which is exactly the claim the floor
    makes, and the only moment the answer is knowable. An unresolved artifact
    records nothing rather than a guess: a source tree has no release identity
    to promise, and an absent floor already reads as unproven to any build
    that does not ship the entry.
    """
    declared = declared_minimum(module)
    if declared != NEXT_RELEASE:
        return declared
    return running_version.strip() or None


def require_declaration(
    entry_name: str,
    source: str,
    module: Any,
    *,
    path: Optional[Path] = None,
) -> Optional[str]:
    """Return the declared floor, refusing declarations that cannot be true.

    This is the authoring gate, and it enforces two things. A surface removal
    must declare a floor at all: a forgettable declaration reproduces the very
    class of failure the declaration exists to prevent, so the entry that
    removes something is required to say what it breaks while its author is
    present to answer.

    And an unreleased entry must declare :data:`NEXT_RELEASE` rather than a
    literal. Every version an author can name today was cut before the entry
    they are writing, so a literal floor on an unreleased entry always names a
    build that cannot serve the schema the entry produces — the failure is
    guaranteed rather than possible. *path* is the entry's file; the check is
    skipped when it is absent or when the file is not in a checkout, which is
    every built artifact, whose bytes are released by definition.
    """
    declared = declared_minimum(module)
    if declared == NEXT_RELEASE:
        return declared
    if declared is not None:
        if path is not None and not entry_is_released(path):
            raise ServingVersionError(
                f"migration entry {entry_name!r} declares "
                f"{DECLARATION_ATTRIBUTE} = {declared!r}, but no release "
                "contains this entry yet, so that version was cut before the "
                "entry existed and cannot serve the schema it produces. "
                f"Declare {DECLARATION_ATTRIBUTE} = {NEXT_RELEASE!r}, which "
                "resolves to the release that actually carries this entry when "
                "it is applied."
            )
        return declared
    if not removes_a_surface(source):
        return None
    raise ServingVersionError(
        f"migration entry {entry_name!r} removes a surface (DROP COLUMN/TABLE) "
        f"but declares no {DECLARATION_ATTRIBUTE}. Set it to "
        f"{NEXT_RELEASE!r} — a new destructive entry can only be served by a "
        "release that does not exist yet — or, for an entry already carried by "
        "a release, to the oldest artifact version in which nothing reads the "
        "removed surface any more."
    )


#: One answer per entry file, keyed by identity rather than name: a history
#: entry is immutable, so the answer cannot change under a running process,
#: and the strand probe and doctor both reload every module repeatedly.
_release_state: Dict[Tuple[str, int, int], bool] = {}


def entry_is_released(path: Path) -> bool:
    """Whether some release tag already contains the commit that added *path*.

    Answered from the checkout the entry lives in, because that is the only
    place the mapping from an entry to the releases carrying it exists. A file
    outside a work tree is part of a built artifact and therefore released;
    so is one whose checkout cannot answer, since refusing to load a history
    on a machine without Git would brick boots for a reason unrelated to
    schema safety. Only a file the checkout positively reports as carried by
    no tag is unreleased.
    """
    try:
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
    except OSError:
        return True
    cached = _release_state.get(key)
    if cached is not None:
        return cached
    released = _released_in_any_tag(path)
    _release_state[key] = released
    return released


def _git(directory: Path, *args: str) -> Optional[str]:
    try:
        done = subprocess.run(
            ("git", "-C", str(directory), *args),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def _released_in_any_tag(path: Path) -> bool:
    directory = path.parent
    if _git(directory, "rev-parse", "--is-inside-work-tree") != "true":
        return True
    commit = _git(
        directory, "log", "--diff-filter=A", "--format=%H", "-1", "--", str(path)
    )
    if commit is None:
        return True
    if not commit:
        return False
    tags = _git(directory, "tag", "--contains", commit)
    return True if tags is None else bool(tags)


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
    or ahead of the entry it carries. So does :data:`NEXT_RELEASE`: the
    artifact applying an entry is the one that carries it, which is precisely
    what that declaration asks for.
    """
    if declared_minimum_version is None or declared_minimum_version == NEXT_RELEASE:
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
    "NEXT_RELEASE",
    "ServingVersionError",
    "declared_minimum",
    "entry_is_released",
    "recorded_floor",
    "refuse_if_behind",
    "removes_a_surface",
    "require_declaration",
    "satisfies_minimum",
    "version_is_unresolved",
]
