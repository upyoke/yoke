"""Retirement switches off flows, sync and the binding and reports attachments."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.file_test_db import apply_test_schema, init_test_db
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.project_github_binding_state import (
    BindingPersistenceState,
    refresh_attached_project_bindings,
)
from yoke_core.domain.project_retirement import set_retirement
from yoke_core.domain.project_retirement_attachments import NO_SECRET_COMMAND
from yoke_core.domain.project_retirement_switch_off import (
    FLOW_RE_ENABLE,
    UNRETIRE_NOTE,
)

NOW = "2026-01-01T00:00:00Z"


def _seed_project(c, project_id: int, slug: str) -> None:
    c.execute(
        "INSERT INTO projects (id, slug, name, public_item_prefix, created_at, "
        "github_sync_mode) VALUES (%s, %s, %s, %s, %s, 'enabled')",
        (project_id, slug, slug.title(), slug[:3].upper(), NOW),
    )
    c.execute(
        "INSERT INTO deployment_flows (id, project_id, name, description, stages, "
        "created_at, status) VALUES (%s, %s, 'Release', '', '[]', %s, 'active')",
        (f"{slug}-release", project_id, NOW),
    )
    c.execute(
        "INSERT INTO project_github_repo_bindings (project_id, installation_id, "
        "repository_id, github_repo, status, last_verified_at, created_at, "
        "updated_at) VALUES (%s, '101', %s, %s, 'active', %s, %s, %s)",
        (project_id, f"5{project_id}", f"example-org/{slug}", NOW, NOW, NOW),
    )


@pytest.fixture
def conn(tmp_path):
    with init_test_db(tmp_path, apply_schema=apply_test_schema):
        c = connect()
        c.execute(
            "INSERT INTO github_app_installations (installation_id, account_id, "
            "account_login, account_type, status, last_verified_at, created_at, "
            "updated_at) VALUES ('101', 'acct-1', 'example-org', 'Organization', "
            "'active', %s, %s, %s)",
            (NOW, NOW, NOW),
        )
        _seed_project(c, 30, "fixture")
        _seed_project(c, 31, "bystander")
        c.execute(
            "INSERT INTO deployment_flows (id, project_id, name, description, "
            "stages, created_at, status) VALUES ('fixture-old', 30, 'Old', '', "
            "'[]', %s, 'disabled')",
            (NOW,),
        )
        c.execute(
            "INSERT INTO sites (id, project_id, name, created_at, settings) "
            "VALUES (300, 30, 'web', %s, %s)",
            (NOW, json.dumps({"deploy_namespace": "fixture"})),
        )
        c.execute(
            "INSERT INTO environments (site, project_id, name, created_at) "
            "VALUES (300, 30, 'production', %s), (300, 30, 'stage', %s)",
            (NOW, NOW),
        )
        c.execute(
            "INSERT INTO project_capabilities (project_id, type, settings, "
            "created_at) VALUES (30, 'github', '{}', %s), "
            "(30, 'setup_command', '{}', %s)",
            (NOW, NOW),
        )
        c.execute(
            "INSERT INTO capability_secrets (project_id, type, key, value, "
            "created_at) VALUES (30, 'aws-admin', 'access_key', 'never-printed', %s)",
            (NOW,),
        )
        c.execute(
            "INSERT INTO qa_plans (id, project_id, slug, name, created_at, "
            "updated_at) VALUES (900, 30, 'smoke', 'Smoke', %s, %s)",
            (NOW, NOW),
        )
        c.execute(
            "INSERT INTO qa_plan_project_defaults (project_id, workflow_id, "
            "transition_id, plan_id, attached_at) VALUES (30, 'dash', 'release', "
            "900, %s)",
            (NOW,),
        )
        c.commit()
        yield c
        c.close()


def _state(conn, project_id):
    flows = conn.execute(
        "SELECT id, status FROM deployment_flows WHERE project_id=%s ORDER BY id",
        (project_id,),
    ).fetchall()
    sync = conn.execute(
        "SELECT github_sync_mode FROM projects WHERE id=%s", (project_id,)
    ).fetchone()[0]
    binding = conn.execute(
        "SELECT status, last_error FROM project_github_repo_bindings "
        "WHERE project_id=%s",
        (project_id,),
    ).fetchone()
    return {r[0]: r[1] for r in flows}, sync, (binding[0], binding[1])


def test_retire_switches_off_and_reports_remaining_attachments(conn):
    result = set_retirement(conn, "fixture", retired=True, reason="QA finished")
    conn.commit()
    flows, sync, binding = _state(conn, 30)
    assert flows == {"fixture-old": "disabled", "fixture-release": "disabled"}
    assert sync == "disabled"
    assert binding == ("unavailable", "project_retired")
    assert result["switched_off"] == {
        "deployment_flows_disabled": ["fixture-release"],
        "github_sync_disabled": True,
        "github_binding_deactivated": True,
    }
    report = result["remaining_attachments"]
    assert "never-printed" not in json.dumps(report)
    assert report[0] == {
        "kind": "capability_secrets",
        "label": "stored credentials",
        "count": 1,
        "names": ["aws-admin.access_key"],
        "commands": [],
        "no_command": NO_SECRET_COMMAND,
    }
    by_kind = {entry["kind"]: entry for entry in report}
    assert [e["kind"] for e in report] == [
        "capability_secrets", "capability_settings", "github_binding",
        "deployment_flows", "environments", "sites", "pack_records",
        "qa_plans", "qa_plan_defaults", "project_roles",
    ]
    counts = {kind: entry["count"] for kind, entry in by_kind.items()}
    assert counts == {
        "capability_secrets": 1, "capability_settings": 2, "github_binding": 1,
        "deployment_flows": 2, "environments": 2, "sites": 1, "pack_records": 0,
        "qa_plans": 1, "qa_plan_defaults": 1, "project_roles": 0,
    }
    unbind = "yoke projects github-binding unbind --project fixture"
    assert by_kind["capability_settings"]["commands"] == [
        unbind,
        "base=$(yoke projects capability-settings get --project fixture "
        "--cap-type setup_command)",
        "yoke projects capability-settings remove --project fixture "
        '--cap-type setup_command --base "$base"',
    ]
    # Yoke's agent hooks refuse a quoted "$(...)" substitution; no recipe uses one.
    assert not any('"$(' in c for e in report for c in e["commands"])
    assert by_kind["github_binding"]["commands"] == [unbind]
    assert by_kind["qa_plans"]["commands"] == [
        "yoke qa plan retire smoke --project fixture --reason 'Project retired'"
    ]
    assert by_kind["qa_plan_defaults"]["commands"] == [
        "yoke qa project-default unset --project fixture --plan-id 900 "
        "--workflow dash --transition release"
    ]
    for kind in ("deployment_flows", "environments", "sites"):
        assert by_kind[kind]["commands"] == [] and by_kind[kind]["no_command"]
    for kind in ("pack_records", "project_roles"):
        assert by_kind[kind]["no_command"] is None  # nothing attached
    # A second project is untouched.
    assert _state(conn, 31) == (
        {"bystander-release": "active"}, "enabled", ("active", None)
    )


def test_repeat_retire_is_idempotent(conn):
    set_retirement(conn, "fixture", retired=True, reason="first")
    again = set_retirement(conn, "fixture", retired=True, reason="second")
    assert again["changed"] is False
    assert again["switched_off"] == {
        "deployment_flows_disabled": [],
        "github_sync_disabled": False,
        "github_binding_deactivated": False,
    }


def test_unretire_leaves_everything_off_and_names_re_enable_commands(conn):
    set_retirement(conn, "fixture", retired=True, reason="QA finished")
    restored = set_retirement(conn, "fixture", retired=False, reason="resume")
    conn.commit()
    assert restored["retired_at"] is None and restored["changed"]
    flows, sync, binding = _state(conn, 30)
    assert set(flows.values()) == {"disabled"}
    assert sync == "disabled"
    assert binding == ("unavailable", "project_retired")
    assert restored["still_off"] == {
        "disabled_deployment_flows": ["fixture-old", "fixture-release"],
        "github_sync_mode": "disabled",
        "github_binding_status": "unavailable",
    }
    assert restored["re_enable"] == [
        # fixture-old was off before retirement: no per-flow re-enable advice.
        FLOW_RE_ENABLE,
        "yoke projects github-binding check --project fixture",
        "yoke projects update --slug fixture --name Fixture --github-sync-mode enabled",
    ]
    assert restored["note"] == UNRETIRE_NOTE
    assert "did not re-enable" in UNRETIRE_NOTE


def test_installation_refresh_keeps_retired_binding_off(conn):
    from datetime import datetime, timezone

    set_retirement(conn, "fixture", retired=True, reason="QA finished")
    set_retirement(conn, "fixture", retired=False, reason="resume")
    refresh_attached_project_bindings(
        conn,
        installation_id="101",
        permissions="{}",
        persistence=BindingPersistenceState("active", None, None),
        verified_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )
    assert _state(conn, 30)[2] == ("unavailable", "project_retired")
    assert _state(conn, 31)[2] == ("active", None)


def test_lifecycle_delivery_skips_until_operator_check(conn):
    from yoke_core.domain.project_github_binding_lifecycle import (
        cmd_apply_project_github_binding_lifecycle,
    )

    set_retirement(conn, "fixture", retired=True, reason="QA finished")
    set_retirement(conn, "fixture", retired=False, reason="resume")
    kwargs = dict(
        installation_id="101",
        repository_id="530",
        installation_status="active",
        repository_available=True,
        conn=conn,
    )
    skipped = cmd_apply_project_github_binding_lifecycle("fixture", **kwargs)
    assert skipped["skipped"] == "binding_switched_off_by_retirement"
    assert _state(conn, 30)[2] == ("unavailable", "project_retired")
    cmd_apply_project_github_binding_lifecycle(
        "fixture", operator_check=True, **kwargs
    )
    assert _state(conn, 30)[2][1] != "project_retired"


def test_cli_prints_credentials_first_with_commands(conn, monkeypatch):
    import io
    from types import SimpleNamespace

    from yoke_cli.commands.adapters.projects_retirement import _write_result
    from yoke_cli.config import machine_config

    monkeypatch.setattr(machine_config, "active_env", lambda: "prod")

    result = set_retirement(conn, "fixture", retired=True, reason="QA finished")
    out = io.StringIO()
    _write_result(SimpleNamespace(result=result), out, io.StringIO())
    text = out.getvalue()
    assert "never-printed" not in text
    first = text.index("stored credentials: 1 (aws-admin.access_key)")
    assert first < text.index("capability settings: 2")
    assert NO_SECRET_COMMAND in text
    assert "run: yoke --env prod projects github-binding unbind --project fixture" in text
    assert "run: base=$(yoke --env prod projects capability-settings get" in text
