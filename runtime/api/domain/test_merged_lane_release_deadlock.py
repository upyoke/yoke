"""The lane row and its directory retire together, so no gate can deadlock.

Three individually-correct behaviours used to compose into a cycle: the merge
removed a lane's directory but left its row ``active``; the verification
tree-binding guard refused any run whose tree was outside that still-active
lane; and the row was released only by the terminal transition the refused
gate was blocking. Transition needed the gate, the gate needed a live lane,
the lane needed the transition.

These tests pin the composition rather than the three parts: that the merge's
own cleanup retires the row, that a stale row still names a recovery a reader
can run, that the override flag the refusal advertises is accepted by both
Command executors, and that the release path can retire a lane whose directory
is already gone only when the branch demonstrably landed.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from yoke_cli.commands.adapters import item_worktree_lane_evidence as lane_evidence
from yoke_core.domain import qa_case_ci_run, qa_case_worktree_run
from yoke_core.domain import verification_tree_binding as tree_binding
from yoke_core.domain.qa_case_execution import QaCaseExecutionError

# The cleanup module and its post-merge helpers import each other, so the
# parent package entry has to be imported first for either to resolve.
from yoke_core.engines import merge_worktree  # noqa: F401
from yoke_core.engines import merge_worktree_cleanup


# --- the merge retires the row in the same act that removes the directory ---


def test_worktree_removal_releases_the_lane_row(monkeypatch, tmp_path) -> None:
    calls: list[dict] = []

    def _dispatcher(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(success=True, result={"released_count": 1})

    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        _dispatcher,
    )
    ctx = SimpleNamespace(
        item_id="1995",
        args=SimpleNamespace(branch="YOK-1995"),
        worktree_path=str(tmp_path / "lane"),
    )

    merge_worktree_cleanup._release_lane_row(ctx)

    assert len(calls) == 1
    assert calls[0]["function_id"] == "item_worktrees.release_merged_lane"
    assert calls[0]["target"].item_id == 1995
    assert calls[0]["payload"] == {"branch": "YOK-1995"}


def test_lane_release_failure_warns_without_unwinding_a_landed_merge(
    monkeypatch, tmp_path, capsys,
) -> None:
    """The merge already landed, so an unreachable control plane only warns."""

    def _dispatcher(**_kwargs):
        raise RuntimeError("control plane unreachable")

    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        _dispatcher,
    )
    ctx = SimpleNamespace(
        item_id="1995",
        args=SimpleNamespace(branch="YOK-1995"),
        worktree_path=str(tmp_path / "lane"),
    )

    merge_worktree_cleanup._release_lane_row(ctx)

    assert "left active after worktree removal" in capsys.readouterr().err


# --- a stale lane names a recovery that exists ---


def _no_free_paths(monkeypatch) -> None:
    """Mute the free-path allowlist.

    ``tmp_path`` lives under the machine temp root, which the allowlist
    passes through unconditionally, so refusal-path assertions need it off.
    """
    monkeypatch.setattr(tree_binding, "_tree_is_free", lambda _tree: False)


def test_refusal_for_a_removed_lane_names_a_runnable_recovery(
    monkeypatch, tmp_path,
) -> None:
    _no_free_paths(monkeypatch)
    missing = str(tmp_path / "gone")
    tree = str(tmp_path / "main")

    refusal = tree_binding.evaluate_tree_binding(
        tree, "session-1", [missing], surface="qa case run", lane_item_id=1995,
    )

    assert refusal is not None
    # The deleted directory is never offered as a place to cd into.
    assert f'cd "{missing}"' not in refusal
    assert "worktree prepare 1995" in refusal
    assert tree_binding.ALLOW_TREE_MISMATCH_FLAG in refusal


def test_refusal_for_a_live_lane_still_names_the_lane_to_cd_into(
    monkeypatch, tmp_path,
) -> None:
    _no_free_paths(monkeypatch)
    lane = tmp_path / "lane"
    lane.mkdir()
    tree = str(tmp_path / "main")

    refusal = tree_binding.evaluate_tree_binding(
        tree, "session-1", [str(lane)], surface="qa case run",
    )

    assert refusal is not None
    assert f'cd "{lane}"' in refusal


def test_a_live_lane_wins_over_a_removed_one_in_the_refusal(
    monkeypatch, tmp_path,
) -> None:
    """A session holding several lanes is pointed at one that still exists."""
    _no_free_paths(monkeypatch)
    missing = str(tmp_path / "gone")
    lane = tmp_path / "lane"
    lane.mkdir()

    refusal = tree_binding.evaluate_tree_binding(
        str(tmp_path / "main"),
        "session-1",
        [missing, str(lane)],
        surface="qa case run",
    )

    assert refusal is not None
    assert f'cd "{lane}"' in refusal


# --- local execution binds to the lane; CI execution binds to a commit ---


def test_worktree_executor_accepts_the_advertised_override(
    monkeypatch, tmp_path,
) -> None:
    """The local-tree refusal names an override that the executor honors."""
    checkout = tmp_path / "main"
    checkout.mkdir()
    seen: dict = {}

    def _evaluate_run(*, surface, tree=None, allow_mismatch=False):
        seen["allow_mismatch"] = allow_mismatch
        if allow_mismatch:
            return tree_binding.TreeBindingVerdict(notice="override")
        return tree_binding.TreeBindingVerdict(refusal="refused")

    monkeypatch.setattr(
        qa_case_worktree_run.verification_tree_binding,
        "evaluate_run",
        _evaluate_run,
    )
    case = {
        "requirement_id": 1,
        "method_config": {"command": "true"},
        "project": "yoke",
        "item_id": 1,
    }

    # Without the flag the guard's refusal still stops the run.
    with pytest.raises(QaCaseExecutionError):
        qa_case_worktree_run.execute_worktree_case(case, checkout_path=checkout)
    assert seen["allow_mismatch"] is False

    # With it, the guard is satisfied and the executor proceeds past binding.
    with pytest.raises(Exception):
        qa_case_worktree_run.execute_worktree_case(
            case, checkout_path=checkout, allow_tree_mismatch=True,
        )
    assert seen["allow_mismatch"] is True


def test_ci_executor_does_not_consult_local_tree_binding(monkeypatch, tmp_path):
    checkout = tmp_path / "main"
    checkout.mkdir()
    monkeypatch.setattr(
        qa_case_ci_run.verification_tree_binding,
        "evaluate_run",
        lambda **_kwargs: pytest.fail("CI consulted local tree binding"),
    )
    assert qa_case_ci_run._resolve_checkout({}, checkout) == checkout.resolve()


# --- releasing a lane whose directory is already gone ---


def _receipt_rows(monkeypatch, rows: list[dict]) -> None:
    """Stand in for the ledger the merge receipt rides on."""
    monkeypatch.setattr(
        "yoke_cli.transport.dispatcher.call_dispatcher",
        lambda **_kwargs: SimpleNamespace(success=True, result={"rows": rows}),
    )
    monkeypatch.setattr(
        "yoke_cli.transport.dispatcher.build_actor",
        lambda **_kwargs: SimpleNamespace(session_id="test-session"),
    )


def _receipt_row(branch: str, *, merge_sha: str) -> dict:
    return {
        "envelope": json.dumps(
            {"context": {"branch": branch, "merge_sha": merge_sha}}
        )
    }


def test_removed_lane_releases_when_its_branch_landed(monkeypatch, tmp_path) -> None:
    _receipt_rows(monkeypatch, [_receipt_row("feature", merge_sha="abc123")])
    lane = {
        "id": 7,
        "branch": "feature",
        "path": str(tmp_path / "already-removed"),
    }

    attestation, error = lane_evidence.attest_releasable_lane(lane)

    assert error is None
    assert attestation is not None
    assert attestation["evidence"] == lane_evidence.EVIDENCE_MERGED_AND_REMOVED


def test_removed_lane_refuses_without_a_merge_receipt(monkeypatch, tmp_path) -> None:
    """A missing directory is never trivially clean on its own."""
    _receipt_rows(monkeypatch, [])
    lane = {
        "id": 8,
        "branch": "feature",
        "path": str(tmp_path / "already-removed"),
    }

    attestation, error = lane_evidence.attest_releasable_lane(lane)

    assert attestation is None
    assert error is not None
    assert "unaccounted for" in error


def test_removed_lane_refuses_on_a_pre_merge_receipt(monkeypatch, tmp_path) -> None:
    """The pre-merge receipt carries no merge sha, so the branch never landed."""
    _receipt_rows(monkeypatch, [_receipt_row("feature", merge_sha="")])
    lane = {
        "id": 9,
        "branch": "feature",
        "path": str(tmp_path / "already-removed"),
    }

    attestation, error = lane_evidence.attest_releasable_lane(lane)

    assert attestation is None
    assert error is not None
    assert "unaccounted for" in error


def test_removed_lane_ignores_another_branchs_receipt(monkeypatch, tmp_path) -> None:
    _receipt_rows(monkeypatch, [_receipt_row("other-branch", merge_sha="abc123")])
    lane = {
        "id": 10,
        "branch": "feature",
        "path": str(tmp_path / "already-removed"),
    }

    attestation, error = lane_evidence.attest_releasable_lane(lane)

    assert attestation is None
    assert error is not None
