"""Commit refusals keep checks enabled and name registered recovery surfaces."""

from __future__ import annotations

import inspect
import shlex
from unittest.mock import patch

import pytest

from yoke_cli.main import main as cli_main
from yoke_core.domain import check_path_claim_coverage_at_commit as coverage
from yoke_core.domain import check_worktree_status_invariant as status
from yoke_harness.git_hooks import pre_commit


@pytest.mark.parametrize("module", [coverage, status, pre_commit])
def test_commit_gates_never_contain_bypass_advice(module):
    # Checking every renderer in each gate also catches unused refusal branches.
    assert "--no-verify" not in inspect.getsource(module)


@pytest.mark.parametrize("paths", [
    ["new.py", "extra.py"],
    ["docs/space name.md", "docs/operator's-guide.md"],
])
def test_emitted_widen_command_runs_through_cli(paths):
    public_ref = "APP-42"
    with patch(
        "yoke_core.domain.project_identity_item_ref.item_ref_for_id",
        return_value=public_ref,
    ):
        message = coverage.format_deny(
            item_id=42, claim_id=7, missing_paths=paths, declared_paths=["old.py"],
        )
    command = next(line.strip() for line in message.splitlines()
                   if line.strip().startswith("yoke "))
    args = shlex.split(command)
    assert args[:4] == ["yoke", "claims", "path", "widen"]
    with (
        patch("yoke_cli.commands._helpers.ensure_handlers_loaded"),
        patch("yoke_cli.commands.adapters.claims_path_change."
              "sync_local_snapshot_for_write"),
        patch("yoke_cli.commands.adapters.claims_path_change.dispatch_and_emit",
              return_value=0) as dispatch,
    ):
        assert cli_main(args[1:]) == 0
    request = dispatch.call_args.kwargs
    assert request["function_id"] == "claims.path.widen"
    assert request["payload"] == {
        "claim_id": 7, "add_paths": paths,
        "reason": "cover staged paths", "allow_planned": False,
    }
    assert coverage.files_outside_coverage(
        paths, ["old.py", *request["payload"]["add_paths"]],
    ) == []


@pytest.mark.parametrize("observed", ["refined-idea", "release", "done"])
def test_status_refusal_names_implementation_entry(observed):
    public_ref = "APP-42"
    message = status._format_block(public_ref, observed)
    assert f"items.status is '{observed}'" in message
    assert f"/yoke implement {public_ref}" in message
    assert "--no-verify" not in message
