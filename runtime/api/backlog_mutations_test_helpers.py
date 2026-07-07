"""Shared imports for the ``test_backlog_mutations_*`` split files.

Filename omits the ``test_`` prefix so pytest does not collect it.

The fixtures and seed helpers themselves still live in ``test_backlog`` (they
are shared across that file and the mutations splits). This module just
re-exports them under one stable surface so each split file has a single
``from runtime.api.backlog_mutations_test_helpers import ...`` line instead
of reaching back into the original test module from multiple sites.
"""

from __future__ import annotations

from runtime.api.conftest import insert_item
from runtime.api.fixtures.schema_ddl import SCHEMA_DDL
from runtime.api.test_backlog import (
    _conn,
    _item_field,
    _patch_externals,
    _seed_claim,
    _seed_item,
    _seed_qa_artifact,
    _seed_qa_requirement,
    _seed_qa_run,
    _seed_session,
    _session_attribution,
    tmp_db,  # noqa: F401 — re-exported pytest fixture
)


__all__ = [
    "SCHEMA_DDL",
    "insert_item",
    "_conn",
    "_item_field",
    "_patch_externals",
    "_seed_claim",
    "_seed_item",
    "_seed_qa_artifact",
    "_seed_qa_requirement",
    "_seed_qa_run",
    "_seed_session",
    "_session_attribution",
    "tmp_db",
]
