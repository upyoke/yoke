"""Key a stage's live stage-wide QA executions by their owning session.

A deployment stage's stage-wide (member-less) roster splits into independent
machine groups. The old index admitted one live stage-wide execution per run
and stage, so one session walked every group while the other hosts sat idle.
Re-keying it by session lets each session hold its own live execution over
disjoint groups; begin keeps rosters disjoint under the run lock. No row is
rewritten. An older serving build must drain first: it would read the stage's
newest live row as its own.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.qa_deployment_scope_schema import (
    _EXECUTION_INDEX_SPECS,
    _assert_indexes,
    _index_contract,
    _index_sql,
    _normalized_keys,
)
from yoke_core.domain.schema_common import _table_exists

MINIMUM_SERVING_VERSION = NEXT_RELEASE

_TABLE = "qa_plan_executions"
_STAGE_SPEC = next(
    spec
    for spec in _EXECUTION_INDEX_SPECS
    if spec[0] == "idx_qa_plan_executions_deployment_stage_active"
)


def _rekeyed(conn: Any) -> bool:
    try:
        keys = _index_contract(conn, _TABLE, _STAGE_SPEC[0])[0]
    except AssertionError:
        return False
    return _normalized_keys(keys) == _normalized_keys(_STAGE_SPEC[1])


def apply(conn: Any) -> None:
    """Replace the run-and-stage key with run, stage and owning session."""
    if not _table_exists(conn, _TABLE) or _rekeyed(conn):
        return
    conn.execute(f'DROP INDEX IF EXISTS "{_STAGE_SPEC[0]}"')
    conn.execute(_index_sql(_TABLE, (_STAGE_SPEC,)).rstrip(";"))


def invariants(conn: Any) -> None:
    """Require the session-keyed partial unique index."""
    if _table_exists(conn, _TABLE):
        _assert_indexes(conn, _TABLE, (_STAGE_SPEC,))


__all__ = ["MINIMUM_SERVING_VERSION", "apply", "invariants"]
