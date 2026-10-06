# ruff: noqa: F811
"""Coverage for the ``path-claims`` CLI dispatcher.
The dispatcher opens the canonical DB through
:func:`yoke_core.domain.db_helpers.connect`. These tests
monkeypatch ``_open_conn`` to return the in-memory test connection so
the CLI shape stays decoupled from the on-disk DB.
"""

from __future__ import annotations

import json

from yoke_core.domain import path_claims_dispatch
from runtime.api.domain._path_claims_test_helpers import (  # noqa: F401
    ambient_holder_session,
    conn,
    local_human,
    seed_target,
)
from runtime.api.domain.path_claims_dispatch_test_support import (  # noqa: F401
    capture,
    patch_conn,
    seed_item,
    seed_session,
)


class TestRegisterCmd:
    def test_register_returns_planned_claim(self, patch_conn, capsys):
        actor = local_human(patch_conn)
        item_id = seed_item(patch_conn)
        target = seed_target(patch_conn, path_string="runtime/api/domain")
        seed_session(patch_conn, "sess-xyz")
        rc = path_claims_dispatch.cmd_register(
            [
                "--item",
                f"YOK-{item_id}",
                "--integration-target",
                "main",
                "--paths",
                "runtime/api/domain",
                "--actor-id",
                str(actor),
                "--session-id",
                "sess-xyz",
            ]
        )
        out, _err = capture(capsys)
        assert rc == 0
        payload = json.loads(out.strip())
        assert payload["success"] is True
        assert payload["claim"]["state"] == "planned"
        assert payload["claim"]["registered_by_actor_id"] == actor
        assert payload["claim"]["registered_by_session_id"] == "sess-xyz"
        assert payload["claim"]["target_ids"] == [target]

    def test_register_threads_tentative_paths_to_future_resolver(
        self, patch_conn, capsys
    ):
        actor = local_human(patch_conn)
        item_id = seed_item(patch_conn)
        rc = path_claims_dispatch.cmd_register(
            [
                "--item",
                f"YOK-{item_id}",
                "--integration-target",
                "main",
                "--paths",
                "definite.py,possible.py",
                "--allow-planned",
                "--tentative-paths",
                "possible.py",
                "--actor-id",
                str(actor),
            ]
        )
        out, _err = capture(capsys)
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
        item_id = seed_item(patch_conn)
        rc = path_claims_dispatch.cmd_register(
            [
                "--item",
                f"YOK-{item_id}",
                "--integration-target",
                "main",
                "--paths",
                "possible.py",
                "--tentative-paths",
                "possible.py",
                "--actor-id",
                str(actor),
            ]
        )
        out, err = capture(capsys)
        assert rc == 2
        assert out == ""
        payload = json.loads(err.strip())
        assert payload["code"] == "USAGE"
        assert "--tentative-paths requires --allow-planned" in payload["message"]

    def test_register_unknown_path_exits_validation(self, patch_conn, capsys):
        actor = local_human(patch_conn)
        item_id = seed_item(patch_conn)
        rc = path_claims_dispatch.cmd_register(
            [
                "--item",
                f"YOK-{item_id}",
                "--integration-target",
                "main",
                "--paths",
                "no/such/path",
                "--actor-id",
                str(actor),
            ]
        )
        out, err = capture(capsys)
        assert rc == 1
        payload = json.loads(err.strip())
        assert payload["success"] is False
        assert payload["code"] == "VALIDATION"
        assert "no/such/path" in payload["message"]
        assert out == ""

    def test_register_invalid_item_id_exits_usage(self, patch_conn, capsys):
        rc = path_claims_dispatch.cmd_register(
            [
                "--item",
                "not-a-number",
                "--integration-target",
                "main",
                "--paths",
                "runtime/api/domain",
            ]
        )
        _out, err = capture(capsys)
        assert rc == 2
        payload = json.loads(err.strip())
        assert payload["code"] == "USAGE"


class TestGetCmd:
    def test_get_returns_claim_dict(self, patch_conn, capsys):
        actor = local_human(patch_conn)
        item_id = seed_item(patch_conn)
        seed_target(patch_conn, path_string="runtime/api/domain")
        rc = path_claims_dispatch.cmd_register(
            [
                "--item",
                f"YOK-{item_id}",
                "--integration-target",
                "main",
                "--paths",
                "runtime/api/domain",
                "--actor-id",
                str(actor),
            ]
        )
        out, _ = capture(capsys)
        claim_id = json.loads(out.strip())["claim"]["id"]

        rc = path_claims_dispatch.cmd_get([str(claim_id)])
        out, _ = capture(capsys)
        assert rc == 0
        payload = json.loads(out.strip())
        assert payload["id"] == claim_id
        assert payload["state"] == "planned"

    def test_get_missing_returns_not_found(self, patch_conn, capsys):
        rc = path_claims_dispatch.cmd_get(["999999"])
        _out, err = capture(capsys)
        assert rc == 1
        payload = json.loads(err.strip())
        assert payload["code"] == "NOT_FOUND"
        assert payload["claim_id"] == 999999


class TestListCmd:
    def test_list_returns_reused_claim_for_item(self, patch_conn, capsys):
        actor = local_human(patch_conn)
        item_id = seed_item(patch_conn)
        seed_target(patch_conn, path_string="runtime/api/domain")
        seed_target(patch_conn, path_string="docs/path-claims.md")

        path_claims_dispatch.cmd_register(
            [
                "--item",
                f"YOK-{item_id}",
                "--integration-target",
                "main",
                "--paths",
                "runtime/api/domain",
                "--actor-id",
                str(actor),
            ]
        )
        capsys.readouterr()
        path_claims_dispatch.cmd_register(
            [
                "--item",
                f"YOK-{item_id}",
                "--integration-target",
                "main",
                "--paths",
                "docs/path-claims.md",
                "--actor-id",
                str(actor),
            ]
        )
        capsys.readouterr()

        rc = path_claims_dispatch.cmd_list(["--item", f"YOK-{item_id}"])
        out, _ = capture(capsys)
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
        item_id = seed_item(patch_conn)
        seed_target(patch_conn, path_string="runtime/api/domain")

        path_claims_dispatch.cmd_register(
            [
                "--item",
                f"YOK-{item_id}",
                "--integration-target",
                "main",
                "--paths",
                "runtime/api/domain",
                "--actor-id",
                str(actor),
            ]
        )
        capsys.readouterr()

        rc = path_claims_dispatch.cmd_list(
            ["--item", f"YOK-{item_id}", "--state", "active"]
        )
        out, _ = capture(capsys)
        assert rc == 0
        assert json.loads(out.strip()) == []
