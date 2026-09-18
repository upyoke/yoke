"""The entry that lets a live database hold a merge-candidate review.

``decision_requests.kind`` carries a CHECK listing the kinds a database
admits, and a table that already exists keeps the constraint it was created
with. Until this entry widens it, the merge boundary's very first review
request is refused by the storage layer on every live universe.
"""

from __future__ import annotations

import sqlite3

from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.decision_request_contract import DECISION_REQUEST_KINDS
from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)
from yoke_core.domain.migration_serving_version import removes_a_surface

ENTRY_NAME = "0044_admit_merge_candidate_review_requests"


def _entry():
    """Load the entry the way the applier does: by path, not by import name."""
    directory = history_dir(migration_history_package)
    match = next(
        record for record in ordered_entries(directory)
        if record.name == ENTRY_NAME
    )
    return load_migration_module(directory / f"{match.name}.py", match.name)


entry = _entry()


def _bare_request_table() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE decision_requests (
            id INTEGER PRIMARY KEY,
            kind TEXT NOT NULL,
            subject_key TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
        );
        """
    )
    return conn


def test_the_widened_vocabulary_is_this_entry_s_own():
    """The CHECK values must not track whatever build applies the entry.

    A restored archive replays its history on a build that may already have
    published a sixth kind; reading the live tuple would let that build
    reach backwards and rewrite what this entry produced.
    """
    assert "merge_candidate_review" in entry.ALL_KINDS
    assert set(entry.ALL_KINDS) == set(DECISION_REQUEST_KINDS)


def test_the_entry_is_permissive_and_declares_no_serving_floor():
    """Admitting a value breaks no reader running behind the entry."""
    directory = history_dir(migration_history_package)
    source = (directory / f"{ENTRY_NAME}.py").read_text()

    assert not removes_a_surface(source)
    assert not hasattr(entry, "MINIMUM_SERVING_VERSION")


def test_a_non_postgres_database_is_left_alone_and_replays_clean():
    """It created its table fresh, so it never carried a narrow constraint."""
    conn = _bare_request_table()

    entry.apply(conn)
    entry.apply(conn)

    entry.invariants(conn)


def test_a_database_without_the_table_is_a_no_op():
    conn = sqlite3.connect(":memory:")

    entry.apply(conn)

    entry.invariants(conn)
