"""How long an item or epic-task title may be, per project.

One rule serves every surface that accepts, rejects, or teaches a title:
item creation and title edits, epic-task creation and title edits,
escalation and field-note promotion, the browser's new-item form, and the
doctor scan. Each of those resolves the limit for the project the title
will live in — the selected project when creating, the owning project when
editing, the parent item's project for an epic task — so a project that
one day carries its own limit changes every surface at once and none of
them separately.

Character counting happens here too, so "how long is this title" has one
answer across surfaces: Python counts code points, which is what the
database's ``length()`` counts and what an operator sees typed.

This module stays free of any database dependency by design. A per-project
override is stored DB-side (the ``project-policy`` capability) and resolved
by the DB-aware ``yoke_core.domain.project_title_policy``; that resolver
calls back into ``title_length_error`` here with the resolved value as
``limit``, so a caller with no DB access in scope still gets the shipped
default.
"""

from __future__ import annotations

from typing import Any, Optional, Union

#: The limit every project resolves to absent a stored override.
DEFAULT_TITLE_MAX_LENGTH: int = 100

#: The lowest value a project may configure. Small enough to stay usable,
#: large enough that "resolves to nothing" and "invisible in a listing"
#: stay impossible.
TITLE_MAX_LENGTH_MINIMUM: int = 10

#: A project named by slug or id, or ``None`` when the caller genuinely has
#: no project in hand (a validator running before project resolution).
TitleProject = Union[str, int, None]


def title_max_length(project: TitleProject = None) -> int:
    """The shipped default title character limit.

    A caller that has resolved a project-specific override passes it as
    ``limit`` to :func:`title_length_error` directly; this function is the
    fallback for callers with no override in hand.
    """
    return DEFAULT_TITLE_MAX_LENGTH


def title_max_length_setting_error(value: Any) -> Optional[str]:
    """Why a proposed per-project title-limit *value* is invalid, or ``None``.

    Shared by the settings-save validation path and the doctor scan, so a
    rejected save and a flagged stored value agree on exactly the same
    bound. An integer is required exactly — a non-integral float (``10.5``)
    or a bool (JSON's only other numeric-looking type) is rejected rather
    than silently truncated or coerced.
    """
    if not isinstance(value, int) or isinstance(value, bool):
        return (
            "Title character limit must be an integer of at least "
            f"{TITLE_MAX_LENGTH_MINIMUM} (got {value!r})."
        )
    if value < TITLE_MAX_LENGTH_MINIMUM:
        return (
            f"Title character limit must be at least {TITLE_MAX_LENGTH_MINIMUM} "
            f"(got {value})."
        )
    return None


def title_length_error(
    title: str,
    *,
    project: TitleProject = None,
    subject: str = "Title",
    limit: Optional[int] = None,
) -> Optional[str]:
    """Why *title* is too long for *project*, or ``None`` when it fits.

    *subject* names what is being titled so the refusal reads correctly
    wherever it surfaces. *limit* is a project-specific value the caller
    already resolved from the DB-owned override; omitting it falls back to
    :func:`title_max_length`.
    """
    resolved_limit = title_max_length(project) if limit is None else limit
    length = len(title)
    if length <= resolved_limit:
        return None
    return (
        f"{subject} exceeds {resolved_limit} characters ({length}). "
        "Shorten it or move details to the body."
    )


__all__ = [
    "DEFAULT_TITLE_MAX_LENGTH",
    "TITLE_MAX_LENGTH_MINIMUM",
    "TitleProject",
    "title_length_error",
    "title_max_length",
    "title_max_length_setting_error",
]
