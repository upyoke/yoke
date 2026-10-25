"""Authorized org sessions remain visible without a project binding."""

from io import StringIO
from contextlib import nullcontext
from uuid import uuid4
from types import SimpleNamespace

import pytest

from runtime.api.domain.test_session_registration_scope import (
    register,
    request as registration_request,
    world as world,
)
from yoke_contracts.timestamps import utc_now
from yoke_contracts.board.project_scope import scoped_project_visibility
from yoke_contracts.board.sections_sessions_scope import (
    scoped_org_sessions,
    session_project_label,
    session_rows,
)
from yoke_cli.commands.adapters import sessions_read
from yoke_cli.commands.adapters.session_control_recipient_output import (
    recipient_project,
)
from yoke_core.domain.handlers.sessions_list import handle_sessions_list
from yoke_core.domain.sessions_visible_roster import open_roster_rows
from yoke_core.domain.sessions_history_read import (
    read_ended_session_history,
    read_recent_session_usage_by_machine,
)
from yoke_core.domain.sessions_list_read import list_sessions
from yoke_core.domain import actor_permissions


@pytest.fixture
def roster(world):
    w = world
    register(w, sid="org-owner", machine_id=str(uuid4()))
    register(w, sid="project-owner", project_id=1, machine_scope=False)
    w.conn.execute(
        "UPDATE harness_sessions SET tool_call_count=1,last_tool_call_at=%s,last_heartbeat=%s",
        (utc_now(), utc_now()),
    )
    w.conn.commit()
    return w


def request(w, payload=None, actor=None):
    req = registration_request(w, payload, function="sessions.list")
    if actor is not None:
        req.actor.actor_id = str(actor)
    return req


def rows(w, payload=None, actor=None):
    outcome = handle_sessions_list(
        request(w, {"detail": "full", **(payload or {})}, actor)
    )
    assert outcome.primary_success, outcome.error
    return {r["session_id"]: r for r in outcome.result_payload["rows"]}


def test_roster_shows_org_session_to_owner(roster):
    row = rows(roster)["org-owner"]
    assert (row["project_id"], row["org_id"], row["scope_kind"]) == (
        None,
        roster.org,
        "org",
    )
    assert row["scope"] == "Outside any project"


def test_roster_hides_org_session_from_stranger(roster):
    assert "org-owner" not in rows(roster, actor=roster.stranger)


@pytest.mark.parametrize("detail", ["full", "summary"])
def test_sessions_list_returns_org_id(roster, detail):
    result = handle_sessions_list(request(roster, {"detail": detail})).result_payload
    assert {"org_id", "scope_kind"} <= set(result["fields"])
    row = next(r for r in result["rows"] if r["session_id"] == "org-owner")
    assert row["org_id"] == roster.org


def test_sessions_list_project_filter_excludes_org(roster):
    assert "org-owner" not in rows(roster, {"project": "1"})
    assert "project-owner" in rows(roster, {"project": "1"})


def test_open_roster_includes_own_org_session(roster):
    assert "org-owner" in {
        r["session_id"] for r in open_roster_rows(request(roster), [], 20)
    }
    assert "org-owner" not in {
        r["session_id"] for r in open_roster_rows(request(roster), ["1"], 20)
    }


def test_sessions_list_org_rows_respect_limit_offset(roster):
    for n in range(3):
        register(roster, sid=f"org-page-{n}")
    roster.conn.execute(
        "UPDATE harness_sessions SET last_tool_call_at=%s", (utc_now(),)
    )
    roster.conn.commit()
    pages = [
        list_sessions(
            project_ids=[], org_session_actor_id=roster.owner, limit=1, offset=n
        )
        for n in range(4)
    ]
    assert all(len(p) == 1 and p[0]["org_id"] == roster.org for p in pages)
    assert len({p[0]["session_id"] for p in pages}) == 4


def ended(w):
    w.conn.execute("UPDATE harness_sessions SET ended_at=%s", (utc_now(),))
    w.conn.commit()


def org_rows(w, reader, actor):
    return reader(w.conn, project_ids=[], org_session_actor_id=actor)["rows"]


def test_ended_history_includes_own_org_session(roster):
    ended(roster)
    result = org_rows(roster, read_ended_session_history, roster.owner)
    assert [r["session_id"] for r in result] == ["org-owner"]
    assert result[0]["org_id"] == roster.org
    assert org_rows(roster, read_ended_session_history, roster.stranger) == []


def test_usage_by_machine_includes_own_org_session(roster):
    ended(roster)
    result = org_rows(roster, read_recent_session_usage_by_machine, roster.owner)
    assert [r["session_id"] for r in result] == ["org-owner"]
    assert result[0]["scope_kind"] == "org"
    assert org_rows(roster, read_recent_session_usage_by_machine, roster.stranger) == []


@pytest.mark.parametrize("mode", ["history", "usage_last_24h"])
def test_history_project_filter_excludes_org(roster, mode):
    ended(roster)
    payload = (
        {"history": {"projects": ["1"]}}
        if mode == "history"
        else {"usage_last_24h": True, "projects": ["1"]}
    )
    assert "org-owner" not in rows(roster, payload)
    unscoped = {"history": {}} if mode == "history" else {"usage_last_24h": True}
    assert "org-owner" in rows(roster, unscoped)


def test_org_reader_can_read_another_actors_session(roster):
    actor_permissions.grant_actor_org_role(
        roster.conn, actor_id=roster.stranger, org_id=roster.org, role_name="viewer"
    )
    roster.conn.commit()
    assert "org-owner" in rows(roster, actor=roster.stranger)


def test_owner_without_org_read_still_sees_own_session(roster):
    roster.conn.execute(
        "DELETE FROM actor_org_roles WHERE actor_id=%s", (roster.owner,)
    )
    roster.conn.commit()
    assert "org-owner" in rows(roster)


def test_board_label_outside_any_project():
    assert session_project_label(None, None) == "Outside any project"
    assert session_project_label(None, "invalid") == "—"


class Board:
    def __init__(self, conn):
        self.conn = conn

    def query_quiet(self, sql, params=()):
        return [tuple(r) for r in self.conn.execute(sql, params).fetchall()]


def test_board_authorized_ids_are_not_project_membership(roster):
    db = Board(roster.conn)
    with scoped_project_visibility(()), scoped_org_sessions(("org-owner",)):
        assert [r[0] for r in session_rows(db, scope="all", active_only=True)] == [
            "org-owner"
        ]
        assert "org-owner" not in {
            r[0] for r in session_rows(db, scope="1", active_only=True)
        }
    with scoped_project_visibility(()), scoped_org_sessions(()):
        assert session_rows(db, scope="all", active_only=True) == []
    with scoped_project_visibility(None):
        assert "org-owner" not in {
            r[0] for r in session_rows(db, scope="all", active_only=True)
        }


def test_cli_renders_outside_project(monkeypatch):
    raw = {"fields": ["project", "org_id"], "rows": [{"project": None, "org_id": 7}]}
    output = StringIO()

    def dispatch(**kwargs):
        kwargs["human_writer"](SimpleNamespace(result=raw), output, StringIO())
        return 0

    monkeypatch.setattr(
        "yoke_cli.commands.adapters.list_paging.dispatch_and_emit", dispatch
    )
    assert sessions_read.sessions_list([]) == 0
    assert "outside any project (org 7)" in output.getvalue()
    assert raw["rows"][0]["project"] is None


def test_recipient_output_org_recipient():
    assert (
        recipient_project({"project_id": None, "org_id": 7})
        == "outside any project (org 7)"
    )
    assert recipient_project({"org_name": "Team"}) == "outside any project (org Team)"
    assert recipient_project({"project": "project", "org_id": None}) == "project"


def test_absent_org_field_tolerated():
    assert recipient_project({"project_id": None}) == "—"
    assert recipient_project({}) == "—"


@pytest.mark.parametrize("actor", ["owner", "stranger", None])
def test_board_collector_uses_authenticated_org_authority(roster, monkeypatch, actor):
    from yoke_core.board import data

    for name in (
        "precompute_epic_stats",
        "prefetch_session_occupancy",
        "collect_architecture_rows",
        "frontier_counts",
        "collect_dashboard_data",
        "_zen_check_visibility",
    ):
        monkeypatch.setattr(data, name, lambda *a, **k: {})
    monkeypatch.setattr(
        data,
        "classify_items",
        lambda *a, **k: {k: [] for k in ("active", "pipeline", "backlog", "done")},
    )
    monkeypatch.setattr(
        data, "collect_session_rows", lambda db, **k: session_rows(db, **k)
    )
    config = SimpleNamespace(
        dashboard_sessions_scope="all",
        timeline_widget=False,
        art_frontier_since=None,
        dashboard_recent_sessions=False,
    )
    db = Board(roster.conn)
    db.scalar = lambda *a, **k: 0
    result = data.collect_board_data(
        db,
        scope="all",
        config=config,
        visible_project_ids=[],
        actor_id=getattr(roster, actor) if actor else None,
    )
    assert ("org-owner" in {r[0] for r in result["sessions"]["active"]}) == (
        actor == "owner"
    )


@pytest.mark.parametrize("bound", [True, False])
def test_local_board_uses_proven_binding_or_named_refusal(roster, monkeypatch, bound):
    from yoke_core.board import data, renderer
    from yoke_core.domain import session_actor_binding

    monkeypatch.setattr(renderer, "BoardDB", lambda *a: nullcontext())
    monkeypatch.setattr(renderer, "parse_config", lambda *a, **k: None)
    monkeypatch.setattr(renderer, "parse_art_config", lambda *a, **k: None)
    monkeypatch.setattr(renderer, "_checkout_project_slug", lambda *a: None)
    monkeypatch.setattr(
        renderer, "render_board_from_payload", lambda payload, **k: payload
    )
    monkeypatch.setattr(
        session_actor_binding,
        "resolve_operating_actor",
        lambda conn: session_actor_binding.ActorBinding(
            actor_id=roster.owner if bound else None,
            code="SESSION_ACTOR_UNBOUND",
            detail="Recovery: yoke config bind-actor --actor-id <id>",
        ),
    )
    monkeypatch.setattr(data, "collect_board_data", lambda db, **k: k)
    if not bound:
        with pytest.raises(
            data.BoardDataError, match="SESSION_ACTOR_UNBOUND.*Recovery:"
        ):
            renderer.render_board(None, "all", None)
    else:
        result = renderer.render_board(None, "all", None)
        assert result["actor_id"] == roster.owner
        assert result["visible_project_ids"] is not None


def test_machine_detail_lists_readable_org_sessions(world):
    from yoke_core.domain.machine_detail import machine_detail
    from yoke_core.domain.machine_registry import register_machine

    machine = str(uuid4())
    record, _ = register_machine(
        world.conn,
        machine_id=machine,
        name="Shared host",
        actor_id=world.owner,
        now=utc_now(),
    )
    register(world, sid="machine-org", machine_id=machine)
    register(
        world,
        sid="machine-project",
        project_id=1,
        machine_scope=False,
        machine_id=machine,
    )
    owner_view = machine_detail(world.conn, record=record, actor_id=world.owner)
    scopes = {
        row["session_id"]: (row["project_id"], row["org_id"])
        for row in owner_view["recent_sessions"]
    }
    assert scopes == {"machine-org": (None, world.org), "machine-project": (1, None)}
    assert [project["id"] for project in owner_view["projects"]] == [1]
    stranger_view = machine_detail(world.conn, record=record, actor_id=world.stranger)
    assert stranger_view["recent_sessions"] == []
