"""The roster asks each release line once, however many cards stand on it.

A delivery box is per card, but almost everything behind one is not: the
releases a card is compared against belong to its project, environment and
flow, and the landings every card records all live in two tables. Asking per
card made a board re-read the same releases and re-open the same repository
once for every card it drew, which is the cost these cases pin down.
"""

from __future__ import annotations

import json

from runtime.api.fixtures.backlog_inserts import insert_deployment_run, insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import release_delivery_summary as summary_module
from yoke_core.domain.deployment_run_candidate_containment import (
    NOT_CONTAINED,
    CandidateContainment,
)
from yoke_core.domain.item_merge_receipt_document import record_entry
from yoke_core.domain.release_delivery_summary import (
    ReleaseCandidates,
    recorded_merge_shas_for_items,
)

PROJECT_ID = 1
FLOW = "yoke-hosted-production"
OTHER_FLOW = "yoke-hosted-stage"
ENVIRONMENT_ID = 7
LINEAGE = "d" * 40


def _landing(conn, item_id: int, merge_sha: str) -> None:
    record_entry(
        conn,
        item_id=item_id,
        branch=f"LANE-{item_id}",
        target="main",
        commit_sha=merge_sha,
        merge_sha=merge_sha,
    )


def _succeeded_run(conn, run_id: str, *, carried: list[str]) -> None:
    insert_deployment_run(
        conn,
        id=run_id,
        project_id=PROJECT_ID,
        status="succeeded",
        flow=FLOW,
        target_tier="persistent",
        release_lineage=LINEAGE,
        target_environment_id=ENVIRONMENT_ID,
        carried_work=json.dumps(
            {"items": [{"ref": "YOK-1", "commit_shas": carried}]}
        ),
        completed_at="2026-09-18T00:00:00Z",
    )


def _counting_candidates(monkeypatch, built: list[tuple]):
    """Record every release line the roster resolves candidates for."""
    real = summary_module.ReleaseCandidates

    class _Counted(real):
        def __init__(self, conn, *, project_id, environment_id, flow=""):
            built.append((project_id, environment_id, flow))
            super().__init__(
                conn,
                project_id=project_id,
                environment_id=environment_id,
                flow=flow,
            )

    monkeypatch.setattr(summary_module, "ReleaseCandidates", _Counted)


def test_cards_sharing_a_release_line_resolve_it_once(monkeypatch) -> None:
    """Three release cards on one flow ask their project's releases once."""
    built: list[tuple] = []
    _counting_candidates(monkeypatch, built)
    from yoke_core.domain.item_overview_read import enrich_item_overview_rows

    with test_database() as conn:
        rows = []
        for offset in range(3):
            item_id = 8100 + offset
            insert_item(
                conn,
                id=item_id,
                title=f"releasing {offset}",
                status="release",
                deployment_flow=FLOW,
            )
            _landing(conn, item_id, chr(ord("a") + offset) * 40)
            rows.append({
                "internal_id": item_id,
                "id": item_id,
                "status": "release",
                "workflow_version_id": _version_id(conn, item_id),
                "deployment_flow": FLOW,
            })
        _succeeded_run(conn, "run-1", carried=[])
        conn.commit()
        enriched = enrich_item_overview_rows(rows)

    assert len(enriched) == 3
    # One release line, one resolution — not one per card.
    assert len(built) == 1
    assert built[0][0] == PROJECT_ID
    assert built[0][2] == FLOW


def test_cards_on_different_flows_each_resolve_their_own(monkeypatch) -> None:
    """Two flows are two release lines, and each is asked on its own."""
    built: list[tuple] = []
    _counting_candidates(monkeypatch, built)
    from yoke_core.domain.item_overview_read import enrich_item_overview_rows

    with test_database() as conn:
        rows = []
        for offset, flow in enumerate((FLOW, OTHER_FLOW)):
            item_id = 8200 + offset
            insert_item(
                conn,
                id=item_id,
                title=f"releasing {flow}",
                status="release",
                deployment_flow=flow,
            )
            _landing(conn, item_id, chr(ord("m") + offset) * 40)
            rows.append({
                "internal_id": item_id,
                "id": item_id,
                "status": "release",
                "workflow_version_id": _version_id(conn, item_id),
                "deployment_flow": flow,
            })
        _succeeded_run(conn, "run-1", carried=[])
        conn.commit()
        enrich_item_overview_rows(rows)

    assert len(built) == 2
    assert {entry[2] for entry in built} == {FLOW, OTHER_FLOW}


def test_a_card_with_no_landing_resolves_no_release_line(monkeypatch) -> None:
    """Nothing landed, so there is no release to ask about on its behalf."""
    built: list[tuple] = []
    _counting_candidates(monkeypatch, built)
    from yoke_core.domain.item_overview_read import enrich_item_overview_rows

    with test_database() as conn:
        insert_item(
            conn, id=8300, title="never landed", status="release",
            deployment_flow=FLOW,
        )
        _succeeded_run(conn, "run-1", carried=[])
        conn.commit()
        enriched = enrich_item_overview_rows([{
            "internal_id": 8300,
            "id": 8300,
            "status": "release",
            "workflow_version_id": _version_id(conn, 8300),
            "deployment_flow": FLOW,
        }])

    assert built == []
    assert enriched[0]["delivery"] == {
        "merges": 0, "deployed": 0, "not_deployed": 0, "flow": "",
    }


def test_each_item_keeps_its_own_merges_in_the_batched_read() -> None:
    """One read over many items still answers per item, and omits the empty."""
    with test_database() as conn:
        _landing(conn, 8400, "a" * 40)
        _landing(conn, 8401, "b" * 40)
        conn.commit()
        merges = recorded_merge_shas_for_items(conn, [8400, 8401, 8402])

    assert merges == {8400: ("a" * 40,), 8401: ("b" * 40,)}
    # An item that recorded nothing is absent, never an empty entry.
    assert 8402 not in merges


def test_the_batched_read_of_no_items_asks_nothing() -> None:
    with test_database() as conn:
        assert recorded_merge_shas_for_items(conn, []) == {}


def test_one_candidate_opens_its_sources_once_for_many_commits() -> None:
    """The candidate is the same revision for every commit asked about."""
    opened: list[int] = []

    class _Source:
        origin = "test"
        location = "test"

        def __init__(self) -> None:
            opened.append(1)
            self.resolved: list[str] = []

        def resolve_commit(self, ref: str) -> str:
            self.resolved.append(ref)
            return ref

        def contains_commit(self, candidate: str, commit: str):
            return False

        def adds_nothing(self, candidate: str, commit: str):
            return False

    source = _Source()
    walk = CandidateContainment.__new__(CandidateContainment)
    walk._candidate = LINEAGE
    walk._openers = (lambda: source,)
    walk._opened = None

    verdicts = [walk.contains(sha) for sha in ("a" * 40, "b" * 40, "c" * 40)]

    assert [v.state for v in verdicts] == [NOT_CONTAINED] * 3
    # One source, opened once, and the candidate resolved once for all three.
    assert opened == [1]
    assert source.resolved.count(LINEAGE) == 1


def test_a_candidate_with_no_lineage_answers_without_opening_anything() -> None:
    """No deployed lineage is no comparison, and costs no repository read."""
    with test_database() as conn:
        _succeeded_run(conn, "run-1", carried=[])
        conn.execute("UPDATE deployment_runs SET release_lineage=''")
        conn.commit()
        candidates = ReleaseCandidates(
            conn,
            project_id=PROJECT_ID,
            environment_id=ENVIRONMENT_ID,
            flow=FLOW,
        )
        assert candidates.contains("a" * 40) is False


def _version_id(conn, item_id: int) -> int:
    row = conn.execute(
        "SELECT workflow_version_id FROM items WHERE id = %s", (item_id,)
    ).fetchone()
    return int(row["workflow_version_id"] if hasattr(row, "keys") else row[0])


__all__: list[str] = []
