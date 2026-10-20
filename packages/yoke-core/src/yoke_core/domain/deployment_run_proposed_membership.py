"""Let composition checks judge membership rows that are not inserted yet.

Inserting a ``deployment_run_items`` row takes a key-share lock on its run's
row through the foreign key, which every run writer's ``FOR UPDATE`` waits
behind. So a composition that judges newly enrolled members after inserting
them holds its run for the whole judgement. Instead the judgement runs first,
before the run lock, against the rows enrollment *would* insert: inside
:func:`proposed_membership` every composition reader names its membership
relation through :func:`run_items`, which is the table plus those rows. The
caller then takes the run lock, proves its reads current, and inserts.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from yoke_core.domain.schema_common import _get_columns

_PROPOSED: ContextVar[str | None] = ContextVar("proposed_run_items", default=None)
_TABLE = "deployment_run_items"


def run_items(alias: str = _TABLE) -> str:
    """The membership relation a composition reader selects from, as *alias*.

    A reader using it passes statement parameters, so the driver turns the
    doubled percent signs inside proposed values back into one.
    """
    relation = _PROPOSED.get()
    if relation is None:
        return _TABLE if alias == _TABLE else f"{_TABLE} {alias}"
    return f"{relation} {alias}"


def _literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(int(value))
    # Standard-conforming strings: a doubled quote is the only SQL escape,
    # and a doubled percent keeps the driver from reading a placeholder.
    return "'" + str(value).replace("'", "''").replace("%", "%%") + "'"


@contextmanager
def proposed_membership(conn: Any, run_id: str, rows: Mapping[int, Mapping[str, Any]]):
    """Show *rows* (item id to column values) as members of *run_id* meanwhile.

    A proposed row carries ``run_id``, ``item_id`` and an ``added_at`` of now,
    plus the columns named in its mapping; every other column reads null.
    """
    if not rows:
        yield
        return
    columns = list(_get_columns(conn, _TABLE))
    proposed = []
    for item_id, values in sorted(rows.items()):
        cells = {**values, "run_id": str(run_id), "item_id": int(item_id)}
        proposed.append(
            "SELECT "
            + ",".join(
                "now()" if column == "added_at" else _literal(cells.get(column))
                for column in columns
            )
        )
    relation = (
        f"(SELECT {','.join(columns)} FROM {_TABLE} UNION ALL "
        + " UNION ALL ".join(proposed)
        + ")"
    )
    token = _PROPOSED.set(relation)
    try:
        yield
    finally:
        _PROPOSED.reset(token)


__all__ = ["proposed_membership", "run_items"]
