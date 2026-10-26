"""The steering report's waiting-chains section."""

from __future__ import annotations

from dataclasses import dataclass, replace

from yoke_core.domain.dependency_cycles_read import LiveEdge
from yoke_core.domain.dependency_planning import BlockerDetail
from yoke_core.domain.steering_fleet_report_waiting_chains import (
    HEADING,
    chains_in,
    seat_chains,
    waiting_chain_fingerprint,
    waiting_chain_section,
)

# YOK-1 is in progress; YOK-2, an idea nobody holds, waits on it; YOK-3 is in
# progress behind YOK-2, and YOK-4 and YOK-5 wait on YOK-3.
STAGES = {
    "YOK-1": "implementing",
    "YOK-2": "idea",
    "YOK-3": "implementing",
    "YOK-4": "idea",
    "YOK-5": "idea",
}
EDGES = (
    (21, "YOK-2", "YOK-1", "activation"),
    (22, "YOK-3", "YOK-2", "activation"),
    (23, "YOK-4", "YOK-3", "integration"),
    (24, "YOK-5", "YOK-3", "activation"),
)


def _facts(ref: str) -> dict:
    stage = STAGES[ref]
    return {"project_id": 1, "status": stage, "unstarted": stage == "idea"}


def _live(edges=EDGES) -> list[LiveEdge]:
    return [
        LiveEdge(
            dependent_ref=dependent,
            detail=BlockerDetail(
                blocking_item=blocker,
                blocking_status=STAGES[blocker],
                gate_point=gate,
                satisfaction="status:done",
                rationale="",
                reason="",
                dependency_id=dependency_id,
            ),
            dependent=_facts(dependent),
            blocker_id=int(blocker.split("-")[1]),
            blocker=_facts(blocker),
        )
        for dependency_id, dependent, blocker, gate in edges
    ]


@dataclass
class _Report:
    waiting_chains: tuple = ()


def test_an_unstarted_mid_chain_blocker_is_flagged_above_the_head():
    # YOK-3 holds two items but waits on YOK-2 and is started, so the head
    # row already counts it: it does not print a row of its own.
    flagged, head = chains_in(_live(), staffed={"YOK-1"})

    assert flagged.blocker == "YOK-2"
    assert flagged.unstarted and not flagged.staffed
    assert flagged.in_progress == ("YOK-3",)
    assert (flagged.unblocks, flagged.depth) == (3, 2)
    assert flagged.waits_on == ("YOK-1",)
    assert head.blocker == "YOK-1" and not head.unstarted
    assert (head.unblocks, head.depth) == (4, 3)

    lines = waiting_chain_section(_Report((flagged, head)))
    assert lines[0] == f"{HEADING}:"
    assert lines[1] == (
        "  ! YOK-2 (idea, unstaffed) unstarted while YOK-3 in progress; "
        "unblocks 3, 2 deep; holds YOK-3 (activation status:done #22); "
        "waits on YOK-1"
    )
    assert lines[2] == (
        "  YOK-1 (implementing, staffed) unblocks 4, 3 deep; "
        "holds YOK-2 (activation status:done #21)"
    )
    assert len(lines) == 3
    assert waiting_chain_fingerprint(_Report((flagged, head))) == [
        ("YOK-1", False),
        ("YOK-2", True),
    ]


def test_an_unstarted_blocker_with_nothing_in_progress_behind_it_is_not_flagged():
    edges = ((31, "YOK-4", "YOK-2", "activation"), (32, "YOK-5", "YOK-2", "closure"))
    [head] = chains_in(_live(edges), staffed=set())

    assert head.blocker == "YOK-2" and not head.unstarted
    assert (head.unblocks, head.depth) == (2, 1)
    assert chains_in(_live(edges[:1]), staffed=set()) == []
    # A claim on the blocker means someone has started it.
    assert not chains_in(_live(EDGES), staffed={"YOK-2"})[0].unstarted


def test_a_narrowed_seat_sees_only_chains_through_its_items():
    chain = chains_in(_live(), staffed=set())[0]
    held = replace(chain, member_ids=frozenset({2, 3}))
    assert seat_chains((held,), None) == (held,)
    assert seat_chains((held,), {3}) == (held,)
    assert seat_chains((held,), {9}) == ()


def test_a_stored_chain_appears_in_the_composed_fleet_report(test_db):
    from runtime.api.fixtures.backlog import insert_item
    from runtime.api.steering_fleet_test_helpers import compose, seed_steering_scope
    from yoke_core.domain.steering_fleet_report_projection import report_dict
    from yoke_core.domain.steering_fleet_report_render import (
        report_body,
        scope_actionable_digest,
    )

    conn = seed_steering_scope(test_db)
    conn.execute("UPDATE items SET status = 'implementing' WHERE id = 1")
    insert_item(conn, id=4, title="Built behind the idea", status="implementing")
    insert_item(conn, id=5, title="Waits on the build", status="idea")
    for dependency_id, dependent, blocker, gate in (
        (21, 2, 1, "activation"),
        (22, 4, 2, "activation"),
        (23, 5, 4, "integration"),
    ):
        conn.execute(
            "INSERT INTO item_dependencies (id, dependent_item_id, blocking_item_id, "
            "gate_point, satisfaction, source, rationale, created_at) "
            "VALUES (%s, %s, %s, %s, 'status:done', 'operator', '', now())",
            (dependency_id, dependent, blocker, gate),
        )
    conn.commit()

    report = compose(conn)

    flagged = report.waiting_chains[0]
    assert flagged.blocker == "YOK-2"
    assert flagged.in_progress == ("YOK-4",)
    assert (flagged.unblocks, flagged.depth) == (2, 2)
    head = next(c for c in report.waiting_chains if c.blocker == "YOK-1")
    assert (head.unblocks, head.depth) == (3, 3)
    body = report_body(report)
    assert f"{HEADING}:" in body
    assert "! YOK-2 (idea, unstaffed) unstarted while YOK-4 in progress" in body
    assert f"{HEADING}:" in scope_actionable_digest(report)
    assert report_dict(report)["waiting_chains"][0]["blocker"] == "YOK-2"
