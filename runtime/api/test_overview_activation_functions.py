"""Handler coverage for the overview.* activation-module surface.

Drives the handlers directly with synthetic envelopes against the
``test_db`` fixture (which repoints the ambient authority, so the
handlers' own ``db_helpers.connect()`` lands in the same database):
derivation across each submodule signal, ordering/locking, monotone
latching, and actor-scoped dismissal.
"""

from __future__ import annotations

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.handlers.overview_activation import (
    handle_overview_activation_get,
    handle_overview_module_dismiss,
    handle_overview_module_restore,
)


def _request(function_id, payload=None, actor_id=None, target=None):
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id=actor_id, session_id=""),
        target=target or TargetRef(kind="global"),
        payload=payload or {},
    )


def _get(payload=None, actor_id=None):
    outcome = handle_overview_activation_get(
        _request("overview.activation.get", payload, actor_id),
    )
    assert outcome.primary_success, outcome.error
    return outcome.result_payload


def _modules_by_key(result):
    return {module["key"]: module for module in result["modules"]}


def _seed_session(conn, session_id, *, executor="claude-code", display=None,
                  workspace="/tmp/ws", project_id=1, at=None):
    at = at or iso8601_now()
    conn.execute(
        "INSERT INTO harness_sessions (session_id, executor, "
        "executor_display_name, provider, model, workspace, project_id, "
        "mode, offered_at, last_heartbeat) "
        "VALUES (%s, %s, %s, 'anthropic', 'test-model', %s, %s, 'wait', "
        "%s, %s)",
        (session_id, executor, display, workspace, project_id, at, at),
    )
    conn.commit()


def test_day_zero_reports_first_module_in_progress_rest_locked(test_db):
    test_db.execute("DELETE FROM projects")
    test_db.commit()
    result = _get(payload={"host_facts": {"machine_connected": False}})
    modules = result["modules"]
    assert [m["key"] for m in modules] == [
        "finish_installation_wizard", "connect_harness", "run_onboard",
        "first_deploy",
    ]
    assert [m["state"] for m in modules] == [
        "in_progress", "not_started", "not_started", "not_started",
    ]
    assert all(m["activated_at"] is None for m in modules)
    assert all(m["dismissed"] is False for m in modules)
    wizard = modules[0]
    assert [s["done"] for s in wizard["submodules"]] == [False] * 4
    assert wizard["fully_complete"] is False
    assert result["dismiss_available"] is False
    count = test_db.execute(
        "SELECT COUNT(*) FROM overview_activation_facts"
    ).fetchone()[0]
    assert int(count) == 0


def test_absent_host_facts_leaves_machine_pending_never_done(test_db):
    result = _get()
    wizard = _modules_by_key(result)["finish_installation_wizard"]
    machine = wizard["submodules"][0]
    assert machine["key"] == "machine_universe"
    assert machine["done"] is False
    assert machine["detail"] == "no host machine fact supplied"
    # Projects exist in the fixture, but the required pair is not complete.
    assert wizard["state"] == "in_progress"


def test_machine_fact_plus_project_activates_and_latches_wizard(test_db):
    result = _get(payload={"host_facts": {"machine_connected": True}})
    wizard = _modules_by_key(result)["finish_installation_wizard"]
    assert wizard["state"] == "activated"
    assert wizard["activated_at"]
    # The required pair activates without the recommended tail.
    assert wizard["fully_complete"] is False
    # The next module unlocks in order.
    assert _modules_by_key(result)["connect_harness"]["state"] == "in_progress"
    row = test_db.execute(
        "SELECT activated_at FROM overview_activation_facts "
        "WHERE module_key = 'finish_installation_wizard'"
    ).fetchone()
    assert row is not None


def test_tail_signals_fill_submodules_and_fully_complete(test_db):
    now = iso8601_now()
    test_db.execute(
        "INSERT INTO project_github_repo_bindings (project_id, "
        "installation_id, repository_id, github_repo, permissions, "
        "created_at, updated_at, status) "
        "VALUES (1, '11', '22', 'org/repo', '{}', %s, %s, 'revoked')",
        (now, now),
    )
    test_db.execute(
        "INSERT INTO project_capabilities (project_id, type, settings, "
        "created_at) VALUES (1, 'aws-admin', '{}', %s)",
        (now,),
    )
    test_db.commit()
    result = _get(payload={"host_facts": {"machine_connected": True}})
    wizard = _modules_by_key(result)["finish_installation_wizard"]
    by_key = {s["key"]: s for s in wizard["submodules"]}
    # A revoked binding is not a connection; the declared capability is.
    assert by_key["github"]["done"] is False
    assert by_key["hosting"]["done"] is True
    assert wizard["fully_complete"] is False

    test_db.execute(
        "UPDATE project_github_repo_bindings SET status = 'active'"
    )
    test_db.commit()
    result = _get(payload={"host_facts": {"machine_connected": True}})
    wizard = _modules_by_key(result)["finish_installation_wizard"]
    assert all(s["done"] for s in wizard["submodules"])
    assert wizard["fully_complete"] is True


def test_activation_is_monotone_across_signal_disappearance(test_db):
    _seed_session(test_db, "s-1")
    first = _modules_by_key(_get())["connect_harness"]
    assert first["state"] == "activated"
    activated_at = first["activated_at"]
    test_db.execute("DELETE FROM harness_sessions")
    test_db.commit()
    again = _modules_by_key(_get())["connect_harness"]
    assert again["state"] == "activated"
    assert again["activated_at"] == activated_at
    # A later module activates out of order; earlier ones stay honest.
    assert _modules_by_key(_get())["run_onboard"]["state"] == "not_started"


def test_onboard_and_deploy_signals_activate_their_modules(test_db):
    now = iso8601_now()
    test_db.execute(
        "INSERT INTO project_onboarding_runs (run_id, schema_version, "
        "project_id, branch, status, metadata_json, created_at, updated_at) "
        "VALUES ('run-abc', 1, 1, 'main', 'running', '{}', %s, %s)",
        (now, now),
    )
    test_db.execute(
        "INSERT INTO deployment_runs (id, project_id, flow, status, "
        "created_at) VALUES ('run-20260101-001', 1, 'flow-x', 'failed', %s)",
        (now,),
    )
    test_db.commit()
    modules = _modules_by_key(_get())
    assert modules["run_onboard"]["state"] == "activated"
    # A failed run is not a first deploy.
    assert modules["first_deploy"]["state"] == "not_started"

    test_db.execute(
        "UPDATE deployment_runs SET status = 'succeeded' "
        "WHERE id = 'run-20260101-001'"
    )
    test_db.commit()
    assert _modules_by_key(_get())["first_deploy"]["state"] == "activated"


def test_harness_targets_hit_from_executor_and_surface_values(test_db):
    _seed_session(test_db, "s-cli", executor="claude-code", display=None)
    _seed_session(
        test_db, "s-vsc", executor="claude-code", display="claude-vscode",
    )
    _seed_session(
        test_db, "s-cdx", executor="codex", display="codex-desktop",
    )
    _seed_session(
        test_db, "s-cur", executor="cursor", display="cursor-desktop",
    )
    harness = _modules_by_key(_get())["connect_harness"]
    hits = {t["key"]: t["hit"] for t in harness["targets"]}
    assert hits == {
        "claude-code": True,
        "codex": True,
        "cursor": True,
        "claude-cli": True,
        # No bare codex session: the desktop surface alone lights the family.
        "codex-cli": False,
        # Cursor lights CLI/IDE from display aliases, not bare sessions.
        "cursor-cli": False,
        "claude-vscode": True,
        "cursor-desktop": True,
    }
    labels = [t["label"] for t in harness["targets"]]
    assert labels == [
        "Claude Code", "Codex", "Cursor",
        "Claude CLI", "Codex CLI", "Cursor CLI",
        "Claude in VS Code", "Cursor IDE",
    ]
    assert harness["connected"]["executor"] in {
        "claude-code", "codex", "cursor",
    }
    assert harness["connected"]["at"]


def test_project_rows_carry_most_recent_workspace_or_none(test_db):
    # Explicit id: the fixture template seeds ids without consuming the
    # identity sequence, so a defaulted id would collide with a seeded row.
    test_db.execute(
        "INSERT INTO projects (id, slug, name, created_at) "
        "VALUES (77, 'quiet', 'Quiet', %s)",
        (iso8601_now(),),
    )
    test_db.commit()
    _seed_session(test_db, "s-old", workspace="/w/old",
                  at="2026-01-01T00:00:00+00:00")
    _seed_session(test_db, "s-new", workspace="/w/new",
                  at="2026-06-01T00:00:00+00:00")
    projects = _modules_by_key(_get())["connect_harness"]["projects"]
    by_slug = {p["slug"]: p["workspace"] for p in projects}
    assert by_slug["yoke"] == "/w/new"
    assert by_slug["quiet"] is None


def test_dismiss_requires_actor_and_scopes_to_the_actor(test_db):
    refused = handle_overview_module_dismiss(_request(
        "overview.module.dismiss", {"module_key": "connect_harness"},
    ))
    assert refused.primary_success is False
    assert refused.error.code == "actor_required"

    actor = test_db.execute(
        "SELECT id FROM actors WHERE kind = 'human' ORDER BY id LIMIT 1"
    ).fetchone()[0]
    done = handle_overview_module_dismiss(_request(
        "overview.module.dismiss", {"module_key": "connect_harness"},
        actor_id=str(actor),
    ))
    assert done.primary_success is True
    assert done.result_payload == {
        "module_key": "connect_harness", "dismissed": True,
    }
    # Idempotent re-dismiss keeps one row.
    handle_overview_module_dismiss(_request(
        "overview.module.dismiss", {"module_key": "connect_harness"},
        actor_id=str(actor),
    ))
    count = test_db.execute(
        "SELECT COUNT(*) FROM actor_ui_preferences"
    ).fetchone()[0]
    assert int(count) == 1

    mine = _modules_by_key(_get(actor_id=str(actor)))
    assert mine["connect_harness"]["dismissed"] is True
    assert mine["finish_installation_wizard"]["dismissed"] is False
    # Another caller with no actor sees no dismissals and no dismiss control.
    anonymous = _get()
    assert all(m["dismissed"] is False for m in anonymous["modules"])
    assert anonymous["dismiss_available"] is False

    restored = handle_overview_module_restore(_request(
        "overview.module.restore", {"module_key": "connect_harness"},
        actor_id=str(actor),
    ))
    assert restored.primary_success is True
    assert restored.result_payload["dismissed"] is False
    remaining = test_db.execute(
        "SELECT COUNT(*) FROM actor_ui_preferences"
    ).fetchone()[0]
    assert int(remaining) == 0


@pytest.mark.parametrize("module_key", [None, "", "nope", 7])
def test_dismiss_refuses_unknown_module_keys(test_db, module_key):
    outcome = handle_overview_module_dismiss(_request(
        "overview.module.dismiss", {"module_key": module_key}, actor_id="1",
    ))
    assert outcome.primary_success is False
    assert outcome.error.code == "payload_invalid"


def test_get_validates_target_and_host_facts_shape(test_db):
    wrong_target = handle_overview_activation_get(_request(
        "overview.activation.get",
        target=TargetRef(kind="item", item_id=1),
    ))
    assert wrong_target.error.code == "target_invalid"
    bad_facts = handle_overview_activation_get(_request(
        "overview.activation.get", {"host_facts": "yes"},
    ))
    assert bad_facts.error.code == "payload_invalid"
    bad_flag = handle_overview_activation_get(_request(
        "overview.activation.get",
        {"host_facts": {"machine_connected": "yes"}},
    ))
    assert bad_flag.error.code == "payload_invalid"
