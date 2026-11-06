"""Batched next-action reads retain people, custody and wait timestamps."""

import json

from runtime.api.domain.handlers.sessions_list_handler_test_support import (
    _insert_item_claim,
    _insert_session,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import next_actor_facts as facts
from yoke_core.domain.audiences import create_audience
from yoke_core.domain.next_actor import item_next_actor
from yoke_contracts.timestamps import utc_now


def test_decisions_and_ci_are_read_once_for_many_rows(monkeypatch):
    now = utc_now()
    with test_database() as conn:
        conn.execute(
            "INSERT INTO actors(id,kind,name,created_at) VALUES (%s,'human',%s,%s)",
            (19001, "Reviewer", now),
        )
        audience = create_audience(
            conn, project_id=1, rules=[{"scope_kind": "actor", "scope_id": 19001}]
        )
        for index in range(3):
            sid, iid = f"worker-{index}", 19001 + index
            insert_item(conn, id=iid, title="Ready item", status="implementing")
            _insert_session(conn, sid, last_heartbeat=now, mode="parked")
            _insert_item_claim(conn, sid, iid)
            conn.execute(
                "INSERT INTO decision_requests(kind,subject_type,subject_key,subject_context,"
                "project_id,audience_id,requesting_session_id,created_at) "
                "VALUES ('operator_question','session_question',%s,%s,1,%s,%s,%s)",
                (
                    f"{sid}:approve",
                    json.dumps({"question": "Approve secret", "item_id": iid}),
                    audience,
                    sid,
                    now,
                ),
            )
            conn.execute(
                "INSERT INTO session_ci_run_waits(session_id,project_id,repo,run_id,kind,created_at) "
                "VALUES (%s,1,'example/repo',%s,'selection',%s)",
                (sid, str(index), now),
            )
        conn.commit()
        reads = []
        original = facts._rows

        def counted(conn, sql, params):
            reads.append(sql)
            return original(conn, sql, params)

        monkeypatch.setattr(facts, "_rows", counted)
        sessions, items = facts.next_actor_facts(
            conn,
            session_ids=[f"worker-{index}" for index in range(3)],
            item_ids=range(19001, 19004),
        )
        assert sum("FROM decision_requests" in sql for sql in reads) == 1
        assert sum("FROM session_ci_run_waits" in sql for sql in reads) == 1
        assert sum("JOIN deployment_runs" in sql for sql in reads) == 1
        for index in range(3):
            decision = sessions[f"worker-{index}"]["pending_decision"]
            assert decision["actor"] == "operator"
            assert decision["people"] == [{"actor_id": 19001, "name": "Reviewer"}]
            assert decision["since"]
            assert items[19001 + index]["pending_decision"] == decision
            assert sessions[f"worker-{index}"]["ci_wait"]["actor"] == "ci_or_deploy"
        conn.execute("UPDATE decision_requests SET status='resolved'")
        conn.execute("UPDATE session_ci_run_waits SET conclusion='success'")
        conn.commit()
        sessions, items = facts.next_actor_facts(
            conn, session_ids=["worker-0"], item_ids=[19001]
        )
        assert "pending_decision" not in sessions["worker-0"]
        assert "ci_wait" not in sessions["worker-0"]
        assert item_next_actor(items[19001])["actor"] == "parent_or_steering"


def test_release_approval_overrides_running_release_and_settlement_clears_wait():
    from yoke_core.domain.flow_create import cmd_create

    now = utc_now()
    with test_database() as conn:
        insert_item(conn, id=19005, title="Release member", status="release")
        cmd_create(
            conn,
            "release-proof",
            "yoke",
            "Release proof",
            "",
            json.dumps(
                [{"name": "deploy", "stage_kind": "execution", "step_runner": "auto"}]
            ),
            status="active",
        )
        conn.execute(
            "INSERT INTO deployment_runs(id,project_id,flow,status,current_stage,created_at,started_at) "
            "VALUES ('release-run',1,'release-proof','executing','deploy',%s,%s)",
            (now, now),
        )
        conn.execute(
            "INSERT INTO deployment_run_items(run_id,item_id,added_at) VALUES ('release-run',19005,%s)",
            (now,),
        )
        conn.execute(
            "INSERT INTO actors(id,kind,name,created_at) VALUES (19005,'human','Approver',%s)",
            (now,),
        )
        audience = create_audience(
            conn, project_id=1, rules=[{"scope_kind": "actor", "scope_id": 19005}]
        )
        conn.commit()
        _, items = facts.next_actor_facts(conn, item_ids=[19005])
        assert item_next_actor(items[19005])["actor"] == "ci_or_deploy"
        conn.execute(
            "INSERT INTO decision_requests(kind,subject_type,subject_key,subject_context,"
            "project_id,audience_id,created_at) VALUES ('deployment_stage_approval',"
            "'deployment_stage','release-run:deploy','{}',1,%s,%s)",
            (audience, now),
        )
        conn.commit()
        _, items = facts.next_actor_facts(conn, item_ids=[19005])
        assert item_next_actor(items[19005])["actor"] == "operator"
        assert item_next_actor(items[19005])["people"][0]["name"] == "Approver"
        conn.execute("UPDATE decision_requests SET status='resolved'")
        conn.execute("UPDATE deployment_runs SET status='succeeded'")
        conn.commit()
        _, items = facts.next_actor_facts(conn, item_ids=[19005])
        assert item_next_actor(items[19005])["actor"] == "parent_or_steering"
