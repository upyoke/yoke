"""Where one environment states the path it proves its own revision at.

A project reaches its environments under different prefixes: a tenant
segment differs per environment, and a path naming the wrong one addresses
another tenant's deployment entirely. So an environment states its own path
in the settings document that already holds its per-environment deploy
configuration, and the project-wide capability answers only for environments
that state nothing.

Absent and unusable stay different all the way out to the refusal. Absent
means the project-wide setting applies. Unusable means this environment
tried to state a path and said something that cannot be one — letting the
project's answer stand in there would probe a path this environment never
claimed.

The answer comes back as a plain ``(path, error)`` pair so this module owes
nothing to the readers that fold it together with the project-wide setting.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain import db_backend, json_helper
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.served_revision_probe import origin_relative_path_error
from yoke_core.domain.settings_cas import read_key_path

#: The dot path, inside that document, where the statement lives.
ENVIRONMENT_IDENTITY_PATH = "qa.identity_path"

#: Neither a path nor a reason there is none: this environment said nothing.
UNSTATED: tuple[str, str] = ("", "")


def environment_identity_hint(environment: str) -> str:
    return (
        "set it via: yoke projects environment-settings merge --project "
        f"<project> --environment {environment} --set "
        f"{ENVIRONMENT_IDENTITY_PATH}=/<path>"
    )


def _unusable(environment: str, detail: str) -> tuple[str, str]:
    return (
        "",
        f"environment {environment!r} sets {ENVIRONMENT_IDENTITY_PATH} to a "
        f"value that {detail}; the origin comes from the environment itself "
        "and this setting only selects a path beneath it; "
        f"{environment_identity_hint(environment)}",
    )


def _settings_text(conn: Any, project_id: int, environment: str) -> tuple[Any, str]:
    """The environment's raw settings text, or why it could not be read."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    try:
        row = conn.execute(
            "SELECT settings FROM environments "
            f"WHERE project_id={marker} AND name={marker}",
            (int(project_id), str(environment)),
        ).fetchone()
    except Exception as exc:
        return None, (
            f"the settings of environment {environment!r} could not be read "
            f"({exc}), so whether it states its own served-revision path is "
            "unknown rather than absent"
        )
    return (None if row is None else row[0]), ""


def environment_identity_path(
    conn: Any, project_id: int, environment: str
) -> tuple[str, str]:
    """This environment's own served-revision path, as ``(path, error)``.

    ``("", "")`` means it states none, which is the answer that lets the
    project-wide setting apply.
    """
    if not environment or not _table_exists(conn, "environments"):
        return UNSTATED
    raw, read_error = _settings_text(conn, project_id, environment)
    if read_error:
        return "", read_error
    if not str(raw or "").strip():
        return UNSTATED
    try:
        document = json_helper.loads_text(str(raw))
    except ValueError as exc:
        return "", (
            f"the settings of environment {environment!r} are not readable "
            f"JSON ({exc}), so whether it states its own served-revision "
            "path is unknown rather than absent"
        )
    if not isinstance(document, Mapping):
        return "", (
            f"the settings of environment {environment!r} are not an object, "
            f"so no {ENVIRONMENT_IDENTITY_PATH} can be read from them"
        )
    stated = read_key_path(dict(document), ENVIRONMENT_IDENTITY_PATH)
    if stated is None:
        return UNSTATED
    if not isinstance(stated, str):
        return _unusable(environment, f"is a {type(stated).__name__}, not a path")
    text = stated.strip()
    if not text:
        return _unusable(environment, "is empty")
    shape_error = origin_relative_path_error(text)
    return _unusable(environment, shape_error) if shape_error else (text, "")


__all__ = [
    "ENVIRONMENT_IDENTITY_PATH",
    "environment_identity_hint",
    "environment_identity_path",
]
