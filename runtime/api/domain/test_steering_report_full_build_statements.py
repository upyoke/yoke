"""A full steering report build costs a pinned number of statements.

A seat steering two projects, with claim holders in both, composes the full
report (every inventory section). The count is pinned, and adding holders
must not move it: per-row reads are what made full builds slow.
"""

from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.statement_counter import CountingConnection
from runtime.api.steering_fleet_test_helpers import (
    LONG_AGO,
    NOW,
    STEERING_SESSION,
    seed_session,
    seed_steering_scope,
)
from yoke_core.domain.steering_claims import acquire as acquire_steering
from yoke_core.domain.steering_fleet_report_compose import (
    combined_dict,
    compose_held_reports,
)
from yoke_core.domain.sessions_lifecycle_claim import claim_work
from yoke_core.domain.strategy_docs_defaults import seed_default_docs
from yoke_core.domain.work_claim_targets import make_item_target

SECOND_PROJECT = 2
#: Statements one full build issues for this fleet. Lower is welcome: update
#: the pin. Higher means a reader went back to per-row work. The failed
#: scheduled-prune read adds two universe-wide statements, cached per build.
#: Each next-actor facts read adds one Test Machine wait read for its page.
#: The Test Machine findings add one held-lease read for idle host holds.
FULL_BUILD_STATEMENTS = 154


def _seed(conn):
    seed_steering_scope(conn)
    conn.execute(
        "INSERT INTO projects (id, slug, name, public_item_prefix, org_id, created_at) "
        "SELECT %s, 'second', 'Second', 'SEC', org_id, created_at FROM projects "
        "WHERE id = 1 ON CONFLICT (id) DO NOTHING",
        (SECOND_PROJECT,),
    )
    conn.commit()
    seed_default_docs(conn, SECOND_PROJECT, "Second")
    acquire_steering(
        conn, session_id=STEERING_SESSION, project_id=SECOND_PROJECT, reason="steering"
    )


def _add_holders(conn, start, stop):
    """Holders split across both projects, each claiming its own item."""
    for index in range(start, stop):
        project = 1 if index % 2 == 0 else SECOND_PROJECT
        item_id = 8000 + index
        insert_item(
            conn,
            id=item_id,
            project_id=project,
            project_sequence=item_id,
            workflow_id="dash",
            status="implementing",
        )
        session = f"holder-{index:03d}"
        seed_session(conn, session, project_id=project, last_tool_call_at=LONG_AGO)
        conn.commit()
        claim_work(conn, session_id=session, target=make_item_target(item_id))
    conn.commit()


def _build(conn):
    report = compose_held_reports(
        conn, session_id=STEERING_SESSION, now=NOW, include_inventory=True
    )
    combined_dict(report)
    return report


def test_full_build_statement_count_is_pinned_and_flat(test_db):
    _seed(test_db)
    counts = []
    seeded = 0
    for size in (4, 12, 24):
        _add_holders(test_db, seeded, size)
        seeded = size
        counted = CountingConnection(test_db)
        report = _build(counted)
        holders = [
            holder
            for section in report.sections
            for holder in section.report.holders
            if holder.session_id.startswith("holder-")
        ]
        assert len({holder.session_id for holder in holders}) == size
        assert {section.report.project_id for section in report.sections} == {
            1,
            SECOND_PROJECT,
        }
        counts.append(counted.count)
    assert counts[0] == counts[1] == counts[2], counts
    assert counts[0] == FULL_BUILD_STATEMENTS, counts
