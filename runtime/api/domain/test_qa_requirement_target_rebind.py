"""Rebind QA evidence stranded by an environment declaration change."""

from __future__ import annotations

from runtime.api.domain.qa_requirement_target_rebind_test_support import (
    _hosted_prod_pair as _hosted_prod_pair,
    _identity as _identity,
    _stamp_requirement as _stamp_requirement,
    _yoke_development as _yoke_development,
)


import json

import pytest
from yoke_core.domain.qa_plan_management import QaPlanError
from yoke_core.domain.qa_plan_requirement_snapshot import require_existing_target
from yoke_core.domain.qa_requirement_pass_currency import (
    has_current_passing_run,
)
from yoke_core.domain.qa_requirement_rebind_endpoint_delta import endpoint_delta
from yoke_core.domain.qa_requirement_target_rebind import (
    QaRebindError,
    rebind_requirement,
)
from yoke_core.domain.settings_cas import (
    apply_key_path_assignments,
    parse_settings_object,
)

from runtime.api.fixtures.pg_testdb import test_database


def _insert_yoke_environment(conn, *, name: str) -> int:
    row = conn.execute(
        "INSERT INTO environments(site,project_id,name,created_at) "
        "SELECT s.id, s.project_id, %s, '2026-01-01T00:00:00Z' "
        "FROM sites s JOIN projects p ON p.id=s.project_id "
        "WHERE p.slug='yoke' AND s.name='Yoke API' RETURNING id",
        (name,),
    ).fetchone()
    conn.commit()
    return int(row["id"] if hasattr(row, "keys") else row[0])


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
        other_id = _insert_yoke_environment(conn, name="staging")
        requirement_id = _stamp_requirement(
            conn, item_id=9104, environment_id=environment_id
        )
        raw = conn.execute(
            "SELECT execution_target_json FROM qa_requirements WHERE id=%s",
            (requirement_id,),
        ).fetchone()[0]
        stored = json.loads(str(raw))
        stored["environment"] = dict(stored.get("environment") or {}, id=other_id)
        conn.execute(
            "UPDATE qa_requirements SET execution_target_json=%s,"
            "execution_target_digest=%s WHERE id=%s",
            (json.dumps(stored, sort_keys=True), "0" * 64, requirement_id),
        )
        conn.commit()
        with pytest.raises(QaRebindError) as exc:
            rebind_requirement(
                conn,
                requirement_id=requirement_id,
                rationale="should not move this to another environment",
            )
        message = str(exc.value)
        assert "not the same environment identity" in message
        assert "stored environment.id" in message
        assert str(other_id) in message
        assert "Yoke API/staging" in message


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
