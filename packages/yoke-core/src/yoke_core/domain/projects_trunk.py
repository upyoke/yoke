"""Resolve the trunk branch a Yoke project integrates into.

The trunk used to fall back to the string ``"main"`` whenever the
project row had no usable value. That guess is how work lands on the
wrong base: nothing refuses at the moment the wrong branch is chosen,
and the mistake surfaces much later as an unresolvable ref, a boundary
diff against a tree the item never branched from, or a merge into
somewhere nobody intended.

So the trunk is an obligation with a satisfier ladder rather than a
default. The operator's declared ``projects.default_branch`` is the top
rung; the default branch the project's recorded remote reports —
converged at project snapshot sync — is the rung below it. When neither
answers, this refuses and names the command that fixes it.

:func:`resolve_trunk_safe` keeps the quiet form for callers that only
want the trunk as a hint in an error message, returning ``None`` rather
than raising. It is for narrative, never for choosing a branch to act
on.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.gate_satisfier_facts import (
    DECLARED_DEFAULT_BRANCH,
    DERIVED_DEFAULT_BRANCH,
    load_project_facts,
)
from yoke_core.domain.gate_satisfier_ladder import (
    LadderUnsatisfied,
    require_rung,
)
from yoke_core.domain.gate_satisfier_ladder_catalog import (
    INTEGRATION_TRUNK_LADDER,
)


_RUNG_FACT = {
    "declared_default_branch": DECLARED_DEFAULT_BRANCH,
    "derived_default_branch": DERIVED_DEFAULT_BRANCH,
}


class ProjectNotFound(Exception):
    """Raised when ``project_id`` has no row in the ``projects`` table."""


class TrunkUnspecified(Exception):
    """The project names no trunk, declared or derived."""


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _project_exists(conn: Any, project_id: int) -> bool:
    if not _table_exists(conn, "projects"):
        raise ProjectNotFound(
            f"projects lookup unavailable for {project_id!r}: the projects "
            "table is absent from this database"
        )
    p = _p(conn)
    row = conn.execute(
        f"SELECT 1 FROM projects WHERE id = {p}", (project_id,)
    ).fetchone()
    return row is not None


def resolve_trunk(conn: Any, project_id: int) -> str:
    """Return the trunk branch name for ``project_id``.

    Raises :class:`ProjectNotFound` when the project has no row (or the
    ``projects`` table is unreadable), and :class:`TrunkUnspecified`
    when it has a row but neither the declared nor the derived rung of
    the integration-trunk ladder resolves. The exception message is the
    ladder's own refusal narrative, so it names both rungs and the
    command that supplies the missing one.
    """
    if not _project_exists(conn, project_id):
        raise ProjectNotFound(
            f"project {project_id!r} has no row in projects",
        )
    facts = load_project_facts(conn, project_id)
    try:
        resolution = require_rung(INTEGRATION_TRUNK_LADDER, facts)
    except LadderUnsatisfied as exc:
        raise TrunkUnspecified(exc.message) from exc
    value = facts.value(_RUNG_FACT[resolution.rung_id]).strip()
    if not value:
        raise TrunkUnspecified(
            f"the {resolution.rung_id!r} rung resolved for project "
            f"{project_id!r} but carries no branch name. Set the trunk "
            "explicitly with `yoke projects update --slug <SLUG> "
            "--name <NAME> --default-branch <BRANCH>`."
        )
    return value


def resolve_trunk_safe(
    conn: Any, project_id: int,
) -> Optional[str]:
    """Best-effort trunk lookup for narrative use only.

    Returns the same string :func:`resolve_trunk` would return, or
    ``None`` when the project has no row or names no trunk. Callers use
    this to enrich an error message; a caller about to branch, diff, or
    merge uses :func:`resolve_trunk` and honors its refusal.
    """
    try:
        return resolve_trunk(conn, project_id)
    except (ProjectNotFound, TrunkUnspecified):
        return None


__all__ = [
    "ProjectNotFound",
    "TrunkUnspecified",
    "resolve_trunk",
    "resolve_trunk_safe",
]
