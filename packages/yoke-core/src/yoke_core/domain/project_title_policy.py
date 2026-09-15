"""DB-backed per-project title-limit resolution.

Bridges the DB-free policy in ``yoke_contracts.title_policy`` to the
DB-owned ``project-policy`` capability: this is where a stored per-project
``title_max_length`` override is actually read. Accepts a project named by
slug or id (or ``None``), matching every existing call site's own project
identity, so a caller never has to pre-resolve one shape into the other.
"""

from __future__ import annotations

from typing import Any

# Calls the resolver function rather than importing the constant, so a
# test moving the shipped default (``monkeypatch.setattr(title_policy,
# "DEFAULT_TITLE_MAX_LENGTH", ...)``) is observed here too — importing the
# constant directly would freeze this module's fallback at import time.
from yoke_contracts.title_policy import title_max_length as _shipped_default

from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.project_policy_capabilities import project_policy_value


def resolve_title_max_length(conn: Any, project: Any) -> int:
    """The stored per-project title limit, or the shipped default.

    An unresolvable *project* (missing, or a reference that no longer
    exists) falls back to the default rather than raising: title-length
    policy is a soft check, and a genuinely bad project reference already
    surfaces its own clear error at the write it is part of.
    """
    if project is None:
        return _shipped_default()
    try:
        project_id = resolve_project_id(conn, project)
    except Exception:
        return _shipped_default()
    value = project_policy_value(conn, project_id, "title_max_length")
    if value is None:
        return _shipped_default()
    try:
        return int(value)
    except (TypeError, ValueError):
        return _shipped_default()


__all__ = ["resolve_title_max_length"]
