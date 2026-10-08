# ruff: noqa: F811
"""``path-claims`` dispatcher: conflict listing and the top-level entry point."""

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


class TestConflictsCmd:
    def test_conflicts_returns_empty_array_when_no_overlap(self, patch_conn, capsys):
        rc = path_claims_dispatch.cmd_conflicts([])
        out, _ = capture(capsys)
        assert rc == 0
        assert json.loads(out.strip()) == []

    def test_conflicts_returns_pair_when_overlap_exists(self, patch_conn, capsys):
        from runtime.api.domain._path_claims_test_helpers import SNAP
        from yoke_core.domain.path_claims import activate, register

        actor = local_human(patch_conn)
        item_a = seed_item(patch_conn, item_id=8001)
        item_b = seed_item(patch_conn, item_id=8002)
        target = seed_target(patch_conn, path_string="runtime/api/domain")
        first = register(
            patch_conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
            item_id=item_a,
        )
        activate(patch_conn, claim_id=first, base_commit_sha=SNAP)
        register(
            patch_conn,
            actor_id=actor,
            integration_target="main",
            target_ids=[target],
            item_id=item_b,
            upstream_claim_id=first,
        )
        rc = path_claims_dispatch.cmd_conflicts([])
        out, _ = capture(capsys)
        assert rc == 0
        conflicts = json.loads(out.strip())
        assert len(conflicts) == 1
        assert conflicts[0]["integration_target"] == "main"


class TestMainEntry:
    def test_main_routes_to_subcommand(self, patch_conn, capsys):
        actor = local_human(patch_conn)
        item_id = seed_item(patch_conn)
        seed_target(patch_conn, path_string="runtime/api/domain")
        rc = path_claims_dispatch.main(
            [
                "register",
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
        assert rc == 0

    def test_main_unknown_subcommand_returns_usage_error(self, capsys):
        rc = path_claims_dispatch.main(["bogus"])
        _out, err = capture(capsys)
        assert rc == 2
        payload = json.loads(err.strip())
        assert payload["code"] == "USAGE"

    def test_main_help_returns_zero(self, capsys):
        rc = path_claims_dispatch.main(["--help"])
        out, _ = capture(capsys)
        assert rc == 0
        assert "register" in out
        assert "list" in out
