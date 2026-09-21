"""Rebind QA evidence stranded by an environment declaration change."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement, insert_qa_run
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_execution_environment_target import target_digest
from yoke_core.domain.qa_plan_management import QaPlanError
from yoke_core.domain.qa_plan_requirement_snapshot import require_existing_target
from yoke_core.domain.qa_requirement_pass_currency import (
    attach_execution_target_digest,
    has_current_passing_run,
)
from yoke_core.domain.qa_requirement_target_rebind import (
    QaRebindError,
    rebind_requirement,
)
from yoke_core.domain.qa_requirement_rebind_endpoint_delta import endpoint_delta
from yoke_core.domain.settings_cas import (
    apply_key_path_assignments,
    parse_settings_object,
)


def _yoke_development(conn):
    return conn.execute(
        "SELECT e.id FROM environments e JOIN sites s ON s.id=e.site "
        "JOIN projects p ON p.id=s.project_id "
        "WHERE p.slug='yoke' AND e.name='development'"
    ).fetchone()[0]


def _identity(conn, environment_id):
    from yoke_core.domain.qa_requirement_rebind_identity import _identity_row

    return _identity_row(conn, environment_id)


def _stamp_requirement(conn, *, item_id: int, environment_id: int) -> int:
    from yoke_core.domain.qa_environment_execution_target import (
        environment_execution_target,
    )
    from yoke_core.domain.qa_execution_environment_target import canonical_target

    insert_item(conn, id=item_id, title="Bound case", workflow_id="issue")
    identity = _identity(conn, environment_id)
    target = environment_execution_target(conn, identity, require_runtime_match=False)
    digest = target_digest(target)
    row = insert_qa_requirement(
        conn,
        item_id=item_id,
        qa_kind="command",
        execution_target_json=canonical_target(target),
        execution_target_digest=digest,
    )
    insert_qa_run(
        conn,
        qa_requirement_id=int(row["id"]),
        verdict="pass",
        raw_result=attach_execution_target_digest("{}", digest),
    )
    return int(row["id"])


def test_endpoint_delta_names_scheme_versus_authority() -> None:
    stored = {"endpoints": {"app_url": "https://app.example.test"}}
    scheme = {"endpoints": {"app_url": "http://app.example.test"}}
    host = {"endpoints": {"app_url": "https://other.example.test"}}
    scheme_delta = endpoint_delta(stored, scheme)
    host_delta = endpoint_delta(stored, host)
    assert scheme_delta["authority_changed"] == []
    assert scheme_delta["changed"][0]["kind"] == "scheme"
    assert host_delta["authority_changed"] == ["app_url"]
    assert host_delta["changed"][0]["kind"] == "authority"


def test_rebind_preserves_the_passing_verdict_on_the_live_digest() -> None:
    with test_database() as conn:
        environment_id = _yoke_development(conn)
        requirement_id = _stamp_requirement(
            conn, item_id=9103, environment_id=environment_id
        )
        row = conn.execute(
            "SELECT settings FROM environments WHERE id=%s",
            (int(environment_id),),
        ).fetchone()
        merged = json.dumps(
            apply_key_path_assignments(
                parse_settings_object(str(row[0] or "{}"), what="settings"),
                {"hosts.app": "https://app.example.test"},
            )
        )
        conn.execute(
            "UPDATE environments SET settings=%s WHERE id=%s",
            (merged, int(environment_id)),
        )
        conn.commit()
        result = rebind_requirement(
            conn,
            requirement_id=requirement_id,
            rationale="hosts.app was declared on the same environment",
            actor_id=2,
        )
        assert result["already_current"] is False
        assert result["from_digest"] != result["to_digest"]
        stored = conn.execute(
            "SELECT execution_target_digest, rebound_from_digest, "
            "rebound_from_target_json, rebind_endpoint_delta_json, "
            "rebind_rationale FROM qa_requirements WHERE id=%s",
            (requirement_id,),
        ).fetchone()
        assert stored["execution_target_digest"] == result["to_digest"]
        assert stored["rebound_from_digest"] == result["from_digest"]
        previous = json.loads(str(stored["rebound_from_target_json"]))
        assert isinstance(previous, dict)
        delta = json.loads(str(stored["rebind_endpoint_delta_json"]))
        assert delta["authority_changed"] == []
        assert result["endpoint_delta"]["changed"]
        assert result["from_target"] is not None
        verdict = conn.execute(
            "SELECT verdict FROM qa_runs WHERE qa_requirement_id=%s",
            (requirement_id,),
        ).fetchone()[0]
        assert verdict == "pass"
        assert has_current_passing_run(conn, requirement_id)


def test_rebind_refuses_a_genuinely_different_environment() -> None:
    with test_database() as conn:
        environment_id = _yoke_development(conn)
        requirement_id = _stamp_requirement(
            conn, item_id=9104, environment_id=environment_id
        )
        raw = conn.execute(
            "SELECT execution_target_json FROM qa_requirements WHERE id=%s",
            (requirement_id,),
        ).fetchone()[0]
        stored = json.loads(str(raw))
        stored["site"] = {"name": "other-site"}
        conn.execute(
            "UPDATE qa_requirements SET execution_target_json=%s,"
            "execution_target_digest=%s WHERE id=%s",
            (json.dumps(stored, sort_keys=True), "0" * 64, requirement_id),
        )
        conn.commit()
        with pytest.raises(QaRebindError, match="not the same environment identity"):
            rebind_requirement(
                conn,
                requirement_id=requirement_id,
                rationale="should not move this to another environment",
            )


def test_rebind_refuses_a_repointed_host_on_the_same_environment() -> None:
    with test_database() as conn:
        environment_id = _yoke_development(conn)
        requirement_id = _stamp_requirement(
            conn, item_id=9106, environment_id=environment_id
        )
        raw = conn.execute(
            "SELECT execution_target_json FROM qa_requirements WHERE id=%s",
            (requirement_id,),
        ).fetchone()[0]
        stored = json.loads(str(raw))
        stored["endpoints"] = dict(stored.get("endpoints") or {})
        stored["endpoints"]["app_url"] = "https://app.example.test"
        conn.execute(
            "UPDATE qa_requirements SET execution_target_json=%s,"
            "execution_target_digest=%s WHERE id=%s",
            (json.dumps(stored, sort_keys=True), "0" * 64, requirement_id),
        )
        row = conn.execute(
            "SELECT settings FROM environments WHERE id=%s",
            (int(environment_id),),
        ).fetchone()
        merged = json.dumps(
            apply_key_path_assignments(
                parse_settings_object(str(row[0] or "{}"), what="settings"),
                {"hosts.app": "https://other.example.test"},
            )
        )
        conn.execute(
            "UPDATE environments SET settings=%s, url=%s WHERE id=%s",
            (merged, "https://other.example.test", int(environment_id)),
        )
        conn.commit()
        with pytest.raises(QaRebindError, match="host authority") as exc:
            rebind_requirement(
                conn,
                requirement_id=requirement_id,
                rationale="should not silently follow a host repoint",
            )
        assert "fresh" in str(exc.value)


def test_snapshot_reuse_names_rebind_when_only_declared_facts_moved() -> None:
    with test_database() as conn:
        environment_id = _yoke_development(conn)
        requirement_id = _stamp_requirement(
            conn, item_id=9105, environment_id=environment_id
        )
        from yoke_core.domain.qa_environment_execution_target import (
            environment_execution_target,
        )

        identity = _identity(conn, environment_id)
        current = environment_execution_target(
            conn, identity, require_runtime_match=False
        )
        current = dict(current)
        current["endpoints"] = dict(current.get("endpoints") or {})
        current["endpoints"]["app_url"] = "http://app.example.test"
        row = conn.execute(
            "SELECT id, execution_target_json, execution_target_digest "
            "FROM qa_requirements WHERE id=%s",
            (requirement_id,),
        ).fetchone()
        with pytest.raises(QaPlanError, match="rebind-target") as exc:
            require_existing_target(
                [row],
                execution_target=current,
                subject="item 9105 transition implemented",
            )
        assert "start a fresh" not in str(exc.value)
