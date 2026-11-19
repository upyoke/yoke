"""The merge-queue probe authorizes as project read, not org-global raw read.

A hosted operator holds the project's operator role but not ``db.read.raw``.
These cases authorize every probe dispatch against a real role table, so a
probe that reached for the raw-read surface again would be refused here the
way it was on hosted Stage.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from runtime.api.domain.function_permission_test_support import _conn
from runtime.api.fixtures.actor_roles import seed_project_role
from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest
from yoke_core.domain import merge_queue_route_selection as selection_mod
from yoke_core.domain import yoke_function_registry
from yoke_core.domain.actor_permissions import (
    PERM_DB_READ_RAW,
    ROLE_OPERATOR,
    PermissionDenied,
    require_permission,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.standalone_item_merge import StandaloneMergeOutcome
from yoke_core.domain.yoke_function_dispatch import _ensure_handlers_registered
from yoke_core.domain.yoke_function_permissions import check_dispatch_permission


@pytest.fixture
def operator():
    """An operator on project ``yoke`` who holds no ``db.read.raw``."""
    conn = _conn()
    try:
        project_id = resolve_project_id(conn, "yoke")
        actor_id = seed_human_actor(conn)
        seed_project_role(
            conn,
            actor_id=actor_id,
            project_id=project_id,
            role_name=ROLE_OPERATOR,
            granted_by_actor_id=actor_id,
        )
        outsider_id = seed_human_actor(conn)
        with pytest.raises(PermissionDenied):
            require_permission(
                conn,
                actor_id=actor_id,
                project_id=project_id,
                permission_key=PERM_DB_READ_RAW,
            )
        yield SimpleNamespace(conn=conn, actor_id=actor_id, outsider_id=outsider_id)
    finally:
        conn.close()


def _authorized_dispatch(conn, actor_id, *, declared, seen):
    """Authorize each call as ``actor_id``; answer the capability read."""
    _ensure_handlers_registered()

    def dispatch(*, function_id, target, payload, **_kw):
        seen.append(function_id)
        entry = yoke_function_registry.lookup(function_id)
        assert entry is not None, f"{function_id} must be registered"
        request = FunctionCallRequest(
            function=function_id,
            actor=ActorContext(actor_id=str(actor_id), session_id="s-1"),
            target=target,
            payload=payload,
        )
        permission = check_dispatch_permission(conn, entry, request)
        if permission.error is not None:
            return permission.error
        assert function_id == "projects.capability.has"
        return SimpleNamespace(
            success=True, result={"project": payload["project"], "has": declared}
        )

    return dispatch


def _no_gates(monkeypatch):
    cleared = lambda **_kw: ""  # noqa: E731
    monkeypatch.setattr(selection_mod, "integration_dependency_refusal", cleared)
    monkeypatch.setattr(selection_mod, "candidate_review_refusal", cleared)


def test_operator_without_raw_read_lands_locally_on_no_queue_project(
    operator, monkeypatch
):
    _no_gates(monkeypatch)
    landed: dict = {}

    def fake_standalone(**kwargs):
        landed.update(kwargs)
        return StandaloneMergeOutcome(ok=True, exit_code=0, already_merged=False)

    monkeypatch.setattr(selection_mod, "merge_standalone_branch", fake_standalone)
    seen: list = []
    outcome = selection_mod.route_standalone_landing(
        item_id=1,
        branch="YOK-200",
        target="main",
        repo_root="/tmp/repo",
        project="yoke",
        dispatch=_authorized_dispatch(
            operator.conn, operator.actor_id, declared=False, seen=seen
        ),
    )
    assert outcome.ok, outcome.error
    assert landed["branch"] == "YOK-200"
    assert seen == ["projects.capability.has"]
    assert "db.read.run" not in seen


def test_operator_without_raw_read_sees_declared_queue(operator):
    seen: list = []
    declared, err = selection_mod.project_declares_merge_queue(
        "yoke",
        dispatch=_authorized_dispatch(
            operator.conn, operator.actor_id, declared=True, seen=seen
        ),
    )
    assert declared and err is None
    assert seen == ["projects.capability.has"]


def test_refused_capability_read_still_refuses_the_landing(operator, monkeypatch):
    _no_gates(monkeypatch)

    def forbidden(**_kw):
        raise AssertionError("a refused probe must not land locally")

    monkeypatch.setattr(selection_mod, "merge_standalone_branch", forbidden)
    seen: list = []
    outcome = selection_mod.route_standalone_landing(
        item_id=1,
        branch="YOK-200",
        target="main",
        repo_root="/tmp/repo",
        project="yoke",
        dispatch=_authorized_dispatch(
            operator.conn, operator.outsider_id, declared=False, seen=seen
        ),
    )
    assert not outcome.ok
    assert "merge-queue capability probe failed" in outcome.error
    assert "db.read.run" not in seen
