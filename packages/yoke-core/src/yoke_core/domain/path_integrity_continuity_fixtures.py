"""Seed path continuity ambiguity and conflicting inherited context.

The public fixture catalog owns dispatch; these implementations write malformed
substrate states directly so the observation-only scanner need not create them.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.path_integrity_fixtures_helpers import (
    KIND_DIRECTORY,
    KIND_FILE,
    ROOT,
    _now_parameter,
    _p,
    ensure_project_row,
    mint_snapshot,
    mint_target,
    record_fixture_row,
)
from yoke_core.domain.path_integrity_invariants import (
    INVARIANT_CONTEXT_INHERITANCE,
    INVARIANT_CONTINUITY_DETERMINISM,
)


def fixture_ambiguous_continuity_v1(conn: Any, project_id: str = "fix_cont") -> int:
    ensure_project_row(conn, project_id)
    root_id = mint_target(
        conn,
        project_id=project_id,
        path_string=ROOT,
        kind=KIND_DIRECTORY,
        parent_target_id=None,
    )
    before = mint_target(
        conn,
        project_id=project_id,
        path_string="old.txt",
        kind=KIND_FILE,
        parent_target_id=root_id,
    )
    after_a = mint_target(
        conn,
        project_id=project_id,
        path_string="new_a.txt",
        kind=KIND_FILE,
        parent_target_id=root_id,
    )
    after_b = mint_target(
        conn,
        project_id=project_id,
        path_string="new_b.txt",
        kind=KIND_FILE,
        parent_target_id=root_id,
    )
    p = _p(conn)
    conn.execute(
        "INSERT INTO path_moves "
        "(before_target_id, after_target_id, recorded_event_id, "
        f" recorded_at) VALUES ({p}, {p}, {p}, {p})",
        (before, after_a, "evt-ambig-a", _now_parameter(conn)),
    )
    conn.execute(
        "INSERT INTO path_moves "
        "(before_target_id, after_target_id, recorded_event_id, "
        f" recorded_at) VALUES ({p}, {p}, {p}, {p})",
        (before, after_b, "evt-ambig-b", _now_parameter(conn)),
    )
    mint_snapshot(
        conn,
        project_id=project_id,
        commit_sha="commitcont",
        target_ids=(root_id, before, after_a, after_b),
    )
    return record_fixture_row(
        conn,
        name="ambiguous_continuity_v1",
        description="Two path_moves rows for the same before_target "
        "point to different after_targets with no "
        "more-specific edge.",
        project_id=project_id,
        expected_invariant_kind=INVARIANT_CONTINUITY_DETERMINISM,
    )


def fixture_conflicting_context_inheritance_v1(
    conn: Any, project_id: str = "fix_ctx"
) -> int:
    ensure_project_row(conn, project_id)
    root_id = mint_target(
        conn,
        project_id=project_id,
        path_string=ROOT,
        kind=KIND_DIRECTORY,
        parent_target_id=None,
    )
    before_a = mint_target(
        conn,
        project_id=project_id,
        path_string="old_a.txt",
        kind=KIND_FILE,
        parent_target_id=root_id,
    )
    before_b = mint_target(
        conn,
        project_id=project_id,
        path_string="old_b.txt",
        kind=KIND_FILE,
        parent_target_id=root_id,
    )
    after = mint_target(
        conn,
        project_id=project_id,
        path_string="new.txt",
        kind=KIND_FILE,
        parent_target_id=root_id,
    )
    mint_snapshot(
        conn,
        project_id=project_id,
        commit_sha="commitctx",
        target_ids=(root_id, before_a, before_b, after),
    )
    p = _p(conn)
    conn.execute(
        "INSERT INTO path_context_values "
        "(target_id, context_family, entry_key, value, "
        " recorded_event_id, recorded_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}, {p})",
        (
            before_a,
            "posture",
            "criticality",
            '{"value":"high"}',
            "evt-ctx-a",
            _now_parameter(conn),
        ),
    )
    conn.execute(
        "INSERT INTO path_context_values "
        "(target_id, context_family, entry_key, value, "
        " recorded_event_id, recorded_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p}, {p})",
        (
            before_b,
            "posture",
            "criticality",
            '{"value":"low"}',
            "evt-ctx-b",
            _now_parameter(conn),
        ),
    )
    conn.execute(
        "INSERT INTO path_moves "
        "(before_target_id, after_target_id, recorded_event_id, "
        f" recorded_at) VALUES ({p}, {p}, {p}, {p})",
        (before_a, after, "evt-ctx-a", _now_parameter(conn)),
    )
    conn.execute(
        "INSERT INTO path_moves "
        "(before_target_id, after_target_id, recorded_event_id, "
        f" recorded_at) VALUES ({p}, {p}, {p}, {p})",
        (before_b, after, "evt-ctx-b", _now_parameter(conn)),
    )
    return record_fixture_row(
        conn,
        name="conflicting_context_inheritance_v1",
        description="Two continuity sources project conflicting "
        "path_context_values onto one after-target.",
        project_id=project_id,
        expected_invariant_kind=INVARIANT_CONTEXT_INHERITANCE,
    )
