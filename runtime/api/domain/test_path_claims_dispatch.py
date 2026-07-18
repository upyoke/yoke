# ruff: noqa: F811
"""Coverage for the ``path-claims`` CLI dispatcher.
The dispatcher resolves the canonical DB through
:func:`yoke_core.domain.db_helpers.resolve_db_path`. These tests
monkeypatch ``_open_conn`` to return the in-memory test connection so
the CLI shape stays decoupled from the on-disk DB.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import (
    path_claims_dispatch,
    path_claims_dispatch_amend,
    path_claims_dispatch_state,
)
from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    ambient_holder_session, conn, local_human, seed_target,
    seed_test_holder_for,
)


def _seed_item(conn, *, item_id: int = 9001, project: str = "yoke") -> int:
    project_key = str(project)
    project_id = 2 if project_key == "externalwebapp" else int(project_key) if project_key.isdigit() else 1
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 'item', 'issue', 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', %s, %s)",
        (item_id, project_id, item_id),
    )
    seed_test_holder_for(conn, item_id=item_id)
    conn.commit()
    return item_id


def _seed_session(conn, session_id: str) -> str:
    conn.execute(
        "INSERT INTO harness_sessions (session_id, executor, provider, model, "
        "project_id, execution_lane, capabilities, workspace, mode, offered_at, "
        "last_heartbeat) "
        "VALUES (%s, 'test', 'test', 'test', 1, 'primary', '[]', '/tmp', 'wait', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z')",
        (session_id,),
    )
    conn.commit()
    return session_id


@pytest.fixture
def patch_conn(monkeypatch, conn, ambient_holder_session):  # noqa: F811
    """Use the in-memory conn for every dispatcher surface; pin ambient holder."""
    class _NoCloseConn:
        def __init__(self, inner):
            self._inner = inner

        def execute(self, *a, **kw):
            return self._inner.execute(*a, **kw)

        def executemany(self, *a, **kw):
            return self._inner.executemany(*a, **kw)

        def commit(self):
            return self._inner.commit()

        def close(self):
            return None

    wrapper = _NoCloseConn(conn)
    monkeypatch.setattr(path_claims_dispatch, "_open_conn", lambda: wrapper)
    monkeypatch.setattr(path_claims_dispatch_amend, "open_conn", lambda: wrapper)
    monkeypatch.setattr(path_claims_dispatch_state, "open_conn", lambda: wrapper)
    return conn


def _capture(capsys):
    captured = capsys.readouterr()
    return captured.out, captured.err


class TestRegisterCmd:
    def test_register_returns_planned_claim(self, patch_conn, capsys):
        actor = local_human(patch_conn)
        item_id = _seed_item(patch_conn)
        target = seed_target(patch_conn, path_string="runtime/api/domain")
        _seed_session(patch_conn, "sess-xyz")
        rc = path_claims_dispatch.cmd_register(
            [
                "--item", f"YOK-{item_id}",
                "--integration-target", "main",
                "--paths", "runtime/api/domain",
                "--actor-id", str(actor),
                "--session-id", "sess-xyz",
            ]
        )
        out, _err = _capture(capsys)
        assert rc == 0
        payload = json.loads(out.strip())
        assert payload["success"] is True
        assert payload["claim"]["state"] == "planned"
        assert payload["claim"]["actor_id"] == actor
        assert payload["claim"]["session_id"] == "sess-xyz"
        assert payload["claim"]["target_ids"] == [target]

    def test_register_threads_tentative_paths_to_future_resolver(
        self, patch_conn, capsys
    ):
        actor = local_human(patch_conn)
        item_id = _seed_item(patch_conn)
        rc = path_claims_dispatch.cmd_register(
            [
                "--item", f"YOK-{item_id}",
                "--integration-target", "main",
                "--paths", "definite.py,possible.py",
                "--allow-planned",
                "--tentative-paths", "possible.py",
                "--actor-id", str(actor),
            ]
        )
        out, _err = _capture(capsys)
        assert rc == 0
        payload = json.loads(out.strip())
        states = {
            entry["path_string"]: entry["materialization_state"]
            for entry in payload["claim"]["declared_targets"]
        }
        assert states == {"definite.py": "planned", "possible.py": "tentative"}

    def test_register_rejects_tentative_paths_without_allow_planned(
        self, patch_conn, capsys
    ):
        actor = local_human(patch_conn)
        item_id = _seed_item(patch_conn)
        rc = path_claims_dispatch.cmd_register(
            [
                "--item", f"YOK-{item_id}",
                "--integration-target", "main",
                "--paths", "possible.py",
                "--tentative-paths", "possible.py",
                "--actor-id", str(actor),
            ]
        )
        out, err = _capture(capsys)
        assert rc == 2
        assert out == ""
        payload = json.loads(err.strip())
        assert payload["code"] == "USAGE"
        assert "--tentative-paths requires --allow-planned" in payload["message"]

    def test_register_unknown_path_exits_validation(self, patch_conn, capsys):
        actor = local_human(patch_conn)
        item_id = _seed_item(patch_conn)
        rc = path_claims_dispatch.cmd_register(
            [
                "--item", str(item_id),
                "--integration-target", "main",
                "--paths", "no/such/path",
                "--actor-id", str(actor),
            ]
        )
        out, err = _capture(capsys)
        assert rc == 1
        payload = json.loads(err.strip())
        assert payload["success"] is False
        assert payload["code"] == "VALIDATION"
        assert "no/such/path" in payload["message"]
        assert out == ""

    def test_register_invalid_item_id_exits_usage(self, patch_conn, capsys):
        rc = path_claims_dispatch.cmd_register(
            [
                "--item", "not-a-number",
                "--integration-target", "main",
                "--paths", "runtime/api/domain",
            ]
        )
        _out, err = _capture(capsys)
        assert rc == 2
        payload = json.loads(err.strip())
        assert payload["code"] == "USAGE"


class TestGetCmd:
    def test_get_returns_claim_dict(self, patch_conn, capsys):
        actor = local_human(patch_conn)
        item_id = _seed_item(patch_conn)
        seed_target(patch_conn, path_string="runtime/api/domain")
        rc = path_claims_dispatch.cmd_register(
            [
                "--item", str(item_id),
                "--integration-target", "main",
                "--paths", "runtime/api/domain",
                "--actor-id", str(actor),
            ]
        )
        out, _ = _capture(capsys)
        claim_id = json.loads(out.strip())["claim"]["id"]

        rc = path_claims_dispatch.cmd_get([str(claim_id)])
        out, _ = _capture(capsys)
        assert rc == 0
        payload = json.loads(out.strip())
        assert payload["id"] == claim_id
        assert payload["state"] == "planned"

    def test_get_missing_returns_not_found(self, patch_conn, capsys):
        rc = path_claims_dispatch.cmd_get(["999999"])
        _out, err = _capture(capsys)
        assert rc == 1
        payload = json.loads(err.strip())
        assert payload["code"] == "NOT_FOUND"
        assert payload["claim_id"] == 999999


class TestListCmd:
    def test_list_returns_reused_claim_for_item(self, patch_conn, capsys):
        actor = local_human(patch_conn)
        item_id = _seed_item(patch_conn)
        seed_target(patch_conn, path_string="runtime/api/domain")
        seed_target(patch_conn, path_string="docs/path-claims.md")

        path_claims_dispatch.cmd_register(
            [
                "--item", str(item_id),
                "--integration-target", "main",
                "--paths", "runtime/api/domain",
                "--actor-id", str(actor),
            ]
        )
        capsys.readouterr()
        path_claims_dispatch.cmd_register(
            [
                "--item", str(item_id),
                "--integration-target", "main",
                "--paths", "docs/path-claims.md",
                "--actor-id", str(actor),
            ]
        )
        capsys.readouterr()

        rc = path_claims_dispatch.cmd_list(["--item", str(item_id)])
        out, _ = _capture(capsys)
        assert rc == 0
        claims = json.loads(out.strip())
        assert len(claims) == 1
        assert {c["state"] for c in claims} == {"planned"}
        assert set(claims[0]["declared_paths"]) == {
            "runtime/api/domain",
            "docs/path-claims.md",
        }
        assert claims[0]["amendments"][0]["amendment_kind"] == "widen"

    def test_list_filters_by_state(self, patch_conn, capsys):
        actor = local_human(patch_conn)
        item_id = _seed_item(patch_conn)
        seed_target(patch_conn, path_string="runtime/api/domain")

        path_claims_dispatch.cmd_register(
            [
                "--item", str(item_id),
                "--integration-target", "main",
                "--paths", "runtime/api/domain",
                "--actor-id", str(actor),
            ]
        )
        capsys.readouterr()

        rc = path_claims_dispatch.cmd_list(
            ["--item", str(item_id), "--state", "active"]
        )
        out, _ = _capture(capsys)
        assert rc == 0
        assert json.loads(out.strip()) == []


class TestConflictsCmd:
    def test_conflicts_returns_empty_array_when_no_overlap(self, patch_conn, capsys):
        rc = path_claims_dispatch.cmd_conflicts([])
        out, _ = _capture(capsys)
        assert rc == 0
        assert json.loads(out.strip()) == []

    def test_conflicts_returns_pair_when_overlap_exists(
        self, patch_conn, capsys
    ):
        from yoke_core.domain._path_claims_test_helpers import SNAP
        from yoke_core.domain.path_claims import activate, register

        actor = local_human(patch_conn)
        item_a = _seed_item(patch_conn, item_id=8001)
        item_b = _seed_item(patch_conn, item_id=8002)
        target = seed_target(patch_conn, path_string="runtime/api/domain")
        first = register(
            patch_conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_a,
        )
        activate(patch_conn, claim_id=first, base_commit_sha=SNAP)
        register(
            patch_conn, actor_id=actor, integration_target="main",
            target_ids=[target], item_id=item_b,
            upstream_claim_id=first,
        )
        rc = path_claims_dispatch.cmd_conflicts([])
        out, _ = _capture(capsys)
        assert rc == 0
        conflicts = json.loads(out.strip())
        assert len(conflicts) == 1
        assert conflicts[0]["integration_target"] == "main"


class TestMainEntry:
    def test_main_routes_to_subcommand(self, patch_conn, capsys):
        actor = local_human(patch_conn)
        item_id = _seed_item(patch_conn)
        seed_target(patch_conn, path_string="runtime/api/domain")
        rc = path_claims_dispatch.main(
            [
                "register",
                "--item", str(item_id),
                "--integration-target", "main",
                "--paths", "runtime/api/domain",
                "--actor-id", str(actor),
            ]
        )
        assert rc == 0

    def test_main_unknown_subcommand_returns_usage_error(self, capsys):
        rc = path_claims_dispatch.main(["bogus"])
        _out, err = _capture(capsys)
        assert rc == 2
        payload = json.loads(err.strip())
        assert payload["code"] == "USAGE"

    def test_main_help_returns_zero(self, capsys):
        rc = path_claims_dispatch.main(["--help"])
        out, _ = _capture(capsys)
        assert rc == 0
        assert "register" in out
        assert "list" in out
