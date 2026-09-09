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
"""

from __future__ import annotations

from typing import Optional, Union

#: The limit every project resolves to. Changing this value changes the
#: effective limit everywhere, because no surface carries its own number.
DEFAULT_TITLE_MAX_LENGTH: int = 100

#: A project named by slug or id, or ``None`` when the caller genuinely has
#: no project in hand (a validator running before project resolution).
TitleProject = Union[str, int, None]


def title_max_length(project: TitleProject = None) -> int:
    """The effective title character limit for *project*.

    Every project resolves to :data:`DEFAULT_TITLE_MAX_LENGTH` today. A
    per-project override would be read here and nowhere else, which is why
    callers pass the project rather than reading the constant directly.
    """
    return DEFAULT_TITLE_MAX_LENGTH


def title_length_error(
    title: str,
    *,
    project: TitleProject = None,
    subject: str = "Title",
) -> Optional[str]:
    """Why *title* is too long for *project*, or ``None`` when it fits.

    *subject* names what is being titled so the refusal reads correctly
    wherever it surfaces; the limit and the offending count always come
    from the resolved policy.
    """
    limit = title_max_length(project)
    length = len(title)
    if length <= limit:
        return None
    return (
        f"{subject} exceeds {limit} characters ({length}). "
        "Shorten it or move details to the body."
    )


__all__ = [
    "DEFAULT_TITLE_MAX_LENGTH",
    "TitleProject",
    "title_length_error",
    "title_max_length",
]
