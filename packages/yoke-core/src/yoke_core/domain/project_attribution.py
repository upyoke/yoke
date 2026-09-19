"""Which project an operation belongs to, when the caller named none.

A project argument that falls back to a compiled-in slug attributes one
project's work to another, and does it silently: the row, the relay, or
the event reads exactly like a deliberate write against that project.
An installation whose own project happens to carry the slug never
notices, while every other project's record is quietly wrong.

There are two honest answers instead, and which one a call site owes
depends on what it does with the value:

* Work that writes, relays, or claims on the project's behalf calls
  :func:`required_project` and gets a refusal it can name -- the caller
  can supply the project, and nothing durable lands under a guess.
* Telemetry calls :func:`resolved_project` and records ``""``. Events
  are disposable and must never fail the operation they describe, so an
  unattributed one says so rather than naming a project at random.

Resolution itself is the established one: the caller's explicit value,
else the project the machine config binds to a checkout the call site
names. That checkout is passed in rather than read from the working
directory, because inferring one project's work from wherever a process
happens to be standing is the same guess in a different costume. A call
site that genuinely acts on a checkout has one to hand; a call site
reading a project off a row does not, and gets the refusal instead.
Installed-project and session-item guessing stay excluded throughout.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

ProjectRef = Union[str, int, None]

#: What an unattributed telemetry record carries. Empty is readable as
#: "nobody said", which no project slug ever is.
UNATTRIBUTED = ""


class UnattributedProjectError(ValueError):
    """An operation that needs a project has none, and none can be found."""


def resolved_project(
    project: ProjectRef = None,
    *,
    checkout: str | Path | None = None,
) -> str:
    """The named project, else the one bound to *checkout*, else ``""``.

    With no *checkout* the caller's value is the only source; nothing is
    inferred from where the process is running.
    """
    named = str(project if project is not None else "").strip()
    if named:
        return named
    if checkout is None:
        return UNATTRIBUTED
    from yoke_core.domain.yok_n_parser import item_argument_project

    try:
        bound = item_argument_project(None, cwd=checkout)
    except Exception:  # noqa: BLE001 -- an unreadable config names nothing
        return UNATTRIBUTED
    return str(bound).strip() if bound is not None else UNATTRIBUTED


def required_project(
    project: ProjectRef = None,
    *,
    operation: str,
    checkout: str | Path | None = None,
) -> str:
    """As :func:`resolved_project`, but refuses instead of guessing.

    The refusal names *operation* and both ways to answer it, because a
    caller that reached here has one of them available.
    """
    resolved = resolved_project(project, checkout=checkout)
    if resolved:
        return resolved
    bound = (
        f"No project is bound to {checkout} either. "
        if checkout is not None
        else ""
    )
    raise UnattributedProjectError(
        f"{operation} needs the project it acts on, and none was named. "
        f"{bound}Pass the project explicitly, or register its checkout "
        f"with `yoke project register <checkout> --project-id <id>`."
    )


__all__ = [
    "UNATTRIBUTED",
    "UnattributedProjectError",
    "required_project",
    "resolved_project",
]
