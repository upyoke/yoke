# ruff: noqa: F811
"""Coverage for ambient item ownership on path-claim mutations.
Mutating ``path-claims`` subcommands must refuse non-holder sessions.
Read-only subcommands remain callable for coordination inspection.
The guard reads the ambient harness session from the env-var chain.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.domain._path_claims_test_helpers import (  # noqa: F401
    conn,
    local_human,
    seed_target,
)
from runtime.api.path_claims_ownership_test_support import (  # noqa: F401
    HOLDER_SESSION,
    INTRUDER_SESSION,
    ITEM_ID,
    err_payload,
    patch_conn,
    projection_snapshot,
    seed_item,
    seed_session,
    staged,
)
from yoke_core.domain import (
    path_claims_dispatch,
    path_claims_dispatch_amend,
    path_claims_dispatch_narrow,
    path_claims_dispatch_state,
)
from yoke_core.api.service_client_path_claims import cmd_path_claim_widen


class TestRegister:
    def test_register_denied_for_non_holder(self, staged, monkeypatch, capsys):
        conn = staged["conn"]
        monkeypatch.setenv("YOKE_SESSION_ID", INTRUDER_SESSION)
        before_claims = conn.execute("SELECT COUNT(*) FROM path_claims").fetchone()[0]
        before_targets = conn.execute(
            "SELECT COUNT(*) FROM path_claim_targets"
        ).fetchone()[0]

        rc = path_claims_dispatch.cmd_register(
            [
                "--item",
                f"YOK-{ITEM_ID}",
                "--integration-target",
                "main",
                "--paths",
                "src/foo.py",
                "--actor-id",
                str(staged["actor"]),
            ]
        )
        payload = err_payload(capsys)
        assert rc == 1
        assert payload["code"] == "OWNERSHIP_DENIED"
        assert payload["item_id"] == ITEM_ID
        assert payload["caller_session_id"] == INTRUDER_SESSION
        assert payload["holder_session_id"] == HOLDER_SESSION
        assert "yoke claims work acquire" in payload["recovery"]
        assert payload.get("claim_id") is None
        assert (
            conn.execute("SELECT COUNT(*) FROM path_claims").fetchone()[0]
            == before_claims
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM path_claim_targets").fetchone()[0]
            == before_targets
        )

    def test_register_session_id_flag_does_not_bypass_guard(
        self, staged, monkeypatch, capsys
    ):
        monkeypatch.setenv("YOKE_SESSION_ID", INTRUDER_SESSION)
        rc = path_claims_dispatch.cmd_register(
            [
                "--item",
                f"YOK-{ITEM_ID}",
                "--integration-target",
                "main",
                "--paths",
                "src/foo.py",
                "--actor-id",
                str(staged["actor"]),
                "--session-id",
                HOLDER_SESSION,
            ]
        )
        payload = err_payload(capsys)
        assert rc == 1
        assert payload["code"] == "OWNERSHIP_DENIED"
        assert payload["caller_session_id"] == INTRUDER_SESSION

    def test_register_denied_when_no_work_claim_exists(
        self, patch_conn, monkeypatch, capsys
    ):
        actor = local_human(patch_conn)
        seed_item(patch_conn, item_id=9002)
        seed_target(patch_conn, path_string="src/foo.py")
        seed_session(patch_conn, INTRUDER_SESSION)
        patch_conn.commit()
        monkeypatch.setenv("YOKE_SESSION_ID", INTRUDER_SESSION)
        rc = path_claims_dispatch.cmd_register(
            [
                "--item",
                "YOK-9002",
                "--integration-target",
                "main",
                "--paths",
                "src/foo.py",
                "--actor-id",
                str(actor),
            ]
        )
        payload = err_payload(capsys)
        assert rc == 1
        assert payload["code"] == "OWNERSHIP_DENIED"
        assert payload["holder_session_id"] is None


def _activate(cid):
    return path_claims_dispatch_state.cmd_activate(
        [str(cid), "--base-commit-sha", "deadbeef0001"]
    )


def _release(cid):
    return path_claims_dispatch_state.cmd_release([str(cid), "--reason", "intrude"])


def _cancel(cid):
    return path_claims_dispatch_state.cmd_cancel([str(cid), "--reason", "intrude"])


def _widen(cid):
    return path_claims_dispatch_amend.cmd_widen(
        [str(cid), "--paths", "src/bar.py", "--reason", "intrude"]
    )


def _cancel_amendment(cid):
    return path_claims_dispatch_amend.cmd_cancel_amendment(
        [str(cid), "--amendment-id", "9999", "--reason", "intrude"]
    )


class TestStateAndAmendmentsDeniedForNonHolder:
    @pytest.fixture(autouse=True)
    def _deny_env(self, monkeypatch):
        monkeypatch.setenv("YOKE_SESSION_ID", INTRUDER_SESSION)

    @pytest.mark.parametrize(
        "call",
        [_activate, _release, _cancel, _widen, _cancel_amendment],
        ids=["activate", "release", "cancel", "widen", "cancel_amendment"],
    )
    def test_mutation_denied_and_state_unchanged(self, staged, capsys, call):
        before = projection_snapshot(staged["conn"], staged["claim_id"])
        rc = call(staged["claim_id"])
        payload = err_payload(capsys)
        assert rc == 1
        assert payload["code"] == "OWNERSHIP_DENIED"
        assert payload["claim_id"] == staged["claim_id"]
        assert projection_snapshot(staged["conn"], staged["claim_id"]) == before

    def test_narrow_denied_and_state_unchanged(self, staged, tmp_path, capsys):
        before = projection_snapshot(staged["conn"], staged["claim_id"])
        rc = path_claims_dispatch_narrow.cmd_narrow(
            [
                str(staged["claim_id"]),
                "--drop-paths",
                "src/bar.py",
                "--reason",
                "intrude",
                "--repo-path",
                str(tmp_path),
            ]
        )
        payload = err_payload(capsys)
        assert rc == 1
        assert payload["code"] == "OWNERSHIP_DENIED"
        assert projection_snapshot(staged["conn"], staged["claim_id"]) == before


def _get(cid):
    return path_claims_dispatch.cmd_get([str(cid)])


def _list_for_item(_cid):
    return path_claims_dispatch.cmd_list(["--item", f"YOK-{ITEM_ID}"])


def _conflicts(_cid):
    return path_claims_dispatch.cmd_conflicts(["--integration-target", "main"])


def _boundary(cid):
    return path_claims_dispatch.cmd_boundary([str(cid), "--repo-path", "."])


class TestReadOnlyRemainsAllowedForNonHolder:
    @pytest.fixture(autouse=True)
    def _deny_env(self, monkeypatch):
        monkeypatch.setenv("YOKE_SESSION_ID", INTRUDER_SESSION)

    @pytest.mark.parametrize(
        "call",
        [_get, _list_for_item, _conflicts, _boundary],
        ids=["get", "list", "conflicts", "boundary"],
    )
    def test_read_only_allowed(self, staged, capsys, call):
        rc = call(staged["claim_id"])
        out, _err = capsys.readouterr()
        assert rc == 0
        # Each command emits valid JSON on stdout; just confirm parse succeeds.
        json.loads(out)


class TestServiceClientForwardingObservesGuard:
    def test_path_claim_widen_via_service_client_denied(
        self, staged, monkeypatch, capsys
    ):
        monkeypatch.setenv("YOKE_SESSION_ID", INTRUDER_SESSION)
        before = projection_snapshot(staged["conn"], staged["claim_id"])
        rc = cmd_path_claim_widen(
            [
                str(staged["claim_id"]),
                "--paths",
                "src/bar.py",
                "--reason",
                "intrude-via-service-client",
            ]
        )
        payload = err_payload(capsys)
        assert rc == 1
        assert payload["code"] == "OWNERSHIP_DENIED"
        assert payload["claim_id"] == staged["claim_id"]
        assert payload["caller_session_id"] == INTRUDER_SESSION
        assert payload["holder_session_id"] == HOLDER_SESSION
        assert projection_snapshot(staged["conn"], staged["claim_id"]) == before
