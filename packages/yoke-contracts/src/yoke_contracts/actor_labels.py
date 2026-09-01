"""Actor-label surface vocabulary shared by storage shape and domain logic.

An actor label is always scoped to a *surface*. The surfaces split into two
kinds, and the split is a storage fact rather than a convention:

* A **resolution surface** answers "which actor is this external token?".
  :data:`GITHUB_LABEL_SURFACE` is one: GitHub sync keys off the label, so a
  label must name at most one actor and the table enforces that uniquely.
* The **display surface** answers the opposite question — "what do we call
  this actor?" — and is never used to resolve a token back to an actor. Two
  people can genuinely share a name, so uniqueness on this surface would
  refuse a legitimate second member rather than prevent an ambiguity.

The schema declares uniqueness only over the resolution surfaces, and the
predicate it uses is :data:`DISPLAY_LABEL_SURFACE` — the same constant the
domain writes and reads through. It lives here so the storage predicate and
the domain callers cannot drift into naming the surface differently.
"""

from __future__ import annotations

#: Surface carrying an actor's human-readable name for operator-facing views.
DISPLAY_LABEL_SURFACE = "display"

#: Surface carrying the GitHub token an actor syncs under.
GITHUB_LABEL_SURFACE = "github_label"

#: Surfaces whose labels resolve back to exactly one actor. The schema's
#: partial unique index covers exactly the complement of the display surface,
#: so this tuple documents the membership rather than parameterizing the SQL.
RESOLUTION_LABEL_SURFACES = (GITHUB_LABEL_SURFACE,)


__all__ = [
    "DISPLAY_LABEL_SURFACE",
    "GITHUB_LABEL_SURFACE",
    "RESOLUTION_LABEL_SURFACES",
]
