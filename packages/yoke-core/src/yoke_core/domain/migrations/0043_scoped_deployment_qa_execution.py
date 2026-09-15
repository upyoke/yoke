"""Partition deployment QA execution by pinned stage and run member.

The pre-cutover uniqueness contracts admitted one active execution and one
materialized plan per deployment run.  Advanced deployment flows need those
contracts partitioned by the pinned QA stage, and item-scoped stages need one
partition per attached run member.  Existing run-wide rows remain legacy
subjects: this entry adds no backfill and rewrites no execution, requirement,
result, review, run, or artifact row.

Schema initialization runs additive convergence before ordered history.  That
phase may add the nullable selector columns and the new indexes, but only this
entry removes the obsolete run-wide indexes and replaces subject checks.  The
serving-floor gate therefore requires operators to stop or drain older serving
builds before applying the entry; otherwise an old boot could recreate the
obsolete ``IF NOT EXISTS`` indexes after the cutover.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.qa_deployment_scope_schema import (
    assert_deployment_scope_contract,
    replace_deployment_scope_contract,
)
from yoke_core.domain.schema_common import _table_exists


MINIMUM_SERVING_VERSION = NEXT_RELEASE


def _scope_tables_exist(conn: Any) -> bool:
    tables = ("qa_plan_executions", "qa_requirements")
    present = tuple(_table_exists(conn, table) for table in tables)
    if any(present) and not all(present):
        raise RuntimeError(
            "scoped deployment QA requires both execution and requirement tables"
        )
    return all(present)


def apply(conn: Any) -> None:
    """Install scoped subjects without mutating legacy records."""
    if _scope_tables_exist(conn):
        replace_deployment_scope_contract(conn)


def invariants(conn: Any) -> None:
    """Require the exact constraints and partial unique-index contracts."""
    if _scope_tables_exist(conn):
        assert_deployment_scope_contract(conn)


__all__ = ["MINIMUM_SERVING_VERSION", "apply", "invariants"]
