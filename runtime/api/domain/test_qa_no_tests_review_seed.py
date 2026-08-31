"""A project without a command gets an explicit no-tests floor verdict."""

from __future__ import annotations

import json

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import qa
from yoke_core.domain.project_verification_posture import attest_no_tests
from yoke_core.domain.qa_plan_management import create_plan
from yoke_core.domain.qa_no_tests_review_seed import (
    NO_TESTS_DECLARED_QA_KIND,
    NO_TESTS_DECLARED_VERDICT_LABEL,
    ensure_no_tests_review_requirement,
    review_transition_for_workflow,
)

_REASON = "content-only site; there is no suite to bind"


def _requirements(conn, item_id: int) -> list[dict]:
    return [
        dict(row)
        for row in conn.execute(
            "SELECT qa_kind, qa_phase, blocking_mode, requirement_source, "
            "success_policy, workflow_transition_id FROM qa_requirements "
            "WHERE item_id=%s ORDER BY id",
            (int(item_id),),
        ).fetchall()
    ]


def _seeded_item(conn):
    return insert_item(
        conn,
        id=4242,
        title="Rewrite the landing copy",
        workflow_id="issue",
        status="implementing",
    )


def test_the_transition_is_the_one_the_quick_command_would_have_used() -> None:
    # Reading it from the scope policy rather than naming a stage keeps the
    # substitute landing exactly where the thing it substitutes for lands.
    with test_database() as conn:
        assert review_transition_for_workflow(conn, "issue") == (
            "reviewing-implementation"
        )


def test_an_attested_project_gets_one_blocking_review_requirement() -> None:
    with test_database() as conn:
        item = _seeded_item(conn)
        attest_no_tests(conn, project_id=1, project="yoke", reason=_REASON)

        seeded = ensure_no_tests_review_requirement(
            conn,
            item_id=int(item["id"]),
            transition_id="reviewing-implementation",
        )
        conn.commit()

        assert seeded is not None
        rows = _requirements(conn, int(item["id"]))

    assert len(rows) == 1
    assert rows[0]["qa_kind"] == NO_TESTS_DECLARED_QA_KIND
    assert rows[0]["qa_phase"] == "verification"
    assert rows[0]["blocking_mode"] == "blocking"
    assert rows[0]["requirement_source"] == "seeded_default"
    assert rows[0]["workflow_transition_id"] == "reviewing-implementation"
    # The reviewer reading the gate learns why no command ran.
    assert _REASON in rows[0]["success_policy"]
    assert NO_TESTS_DECLARED_VERDICT_LABEL in rows[0]["success_policy"]
    assert "yoke qa no-tests clear" in rows[0]["success_policy"]
    assert "yoke qa registered-command set" in rows[0]["success_policy"]


def test_seeding_twice_leaves_one_requirement() -> None:
    # A re-entered transition must not double the review a reviewer owes for
    # one change.
    with test_database() as conn:
        item = _seeded_item(conn)
        attest_no_tests(conn, project_id=1, project="yoke", reason=_REASON)

        first = ensure_no_tests_review_requirement(
            conn, item_id=int(item["id"]),
            transition_id="reviewing-implementation",
        )
        second = ensure_no_tests_review_requirement(
            conn, item_id=int(item["id"]),
            transition_id="reviewing-implementation",
        )
        conn.commit()

        assert first == second
        assert len(_requirements(conn, int(item["id"]))) == 1


def test_command_absence_seeds_the_floor_without_a_posture_row() -> None:
    with test_database() as conn:
        item = _seeded_item(conn)

        seeded = ensure_no_tests_review_requirement(
            conn, item_id=int(item["id"]),
            transition_id="reviewing-implementation",
        )
        conn.commit()

        assert seeded is not None
        rows = _requirements(conn, int(item["id"]))

    assert rows[0]["qa_kind"] == NO_TESTS_DECLARED_QA_KIND
    assert NO_TESTS_DECLARED_VERDICT_LABEL in rows[0]["success_policy"]
    assert "yoke qa no-tests clear" not in rows[0]["success_policy"]
    assert "yoke qa registered-command set" in rows[0]["success_policy"]


def test_registered_command_seeds_no_floor_requirement() -> None:
    with test_database() as conn:
        item = _seeded_item(conn)
        create_plan(
            conn,
            project="yoke",
            slug="registered-command-quick",
            name="Quick command",
        )

        seeded = ensure_no_tests_review_requirement(
            conn, item_id=int(item["id"]),
            transition_id="reviewing-implementation",
        )
        conn.commit()

        assert seeded is None
        assert _requirements(conn, int(item["id"])) == []


def test_floor_verdict_is_recorded_as_agent_no_tests_declared() -> None:
    with test_database() as conn:
        item = _seeded_item(conn)
        requirement_id = ensure_no_tests_review_requirement(
            conn, item_id=int(item["id"]),
            transition_id="reviewing-implementation",
        )
        conn.commit()
        run_id = qa.cmd_run_add(
            requirement_id=int(requirement_id),
            performed_by="agent",
            verdict="pass",
            raw_result=NO_TESTS_DECLARED_VERDICT_LABEL,
            head_sha="a" * 40,
        )
        row = conn.execute(
            "SELECT performed_by,qa_kind,verdict,raw_result FROM qa_runs "
            "WHERE id=%s",
            (run_id,),
        ).fetchone()

    assert row["performed_by"] == "agent"
    assert row["qa_kind"] == "no_tests_declared"
    assert row["verdict"] == "pass"
    assert json.loads(row["raw_result"])["evidence"] == (
        "agent-attested / no-tests-declared"
    )


def test_other_transitions_seed_nothing() -> None:
    with test_database() as conn:
        item = _seeded_item(conn)
        attest_no_tests(conn, project_id=1, project="yoke", reason=_REASON)

        seeded = ensure_no_tests_review_requirement(
            conn, item_id=int(item["id"]), transition_id="release",
        )
        conn.commit()

        assert seeded is None
        assert _requirements(conn, int(item["id"])) == []
