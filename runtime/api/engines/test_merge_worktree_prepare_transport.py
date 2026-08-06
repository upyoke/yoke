"""Transport-aware routing regression tests for the merge-worktree prep reads.

The merge preparation phase's control-plane reads must route through the
transport-aware ``call_dispatcher`` facade so the flow works over an https
control plane, not only a local Postgres connection. These tests monkeypatch
``call_dispatcher`` in each prep module namespace and assert every migrated
control-plane touch relays instead of opening a bare local ``mw._connect()``
or shelling out through ``mw._run_python_module``, with the preflight
block/OK verdicts preserved.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.engines import merge_worktree as mw
from yoke_core.engines import merge_worktree_prepare as prep
from yoke_core.engines import merge_worktree_prepare_preflight as pf
from yoke_core.engines import merge_worktree_prepare_state as st
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext

# Synthetic fixture id kept off the bare literal so the doc-hygiene drift guard stays clean.
TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


def _resp(function_id, result=None, *, success=True):
    return FunctionCallResponse(
        success=success, function=function_id, version="v1", result=result or {}
    )


def _no_bare_db(monkeypatch):
    """Fail the test if any migrated path opens a bare connect / subprocess."""
    monkeypatch.setattr(
        mw, "_connect",
        lambda *_a, **_k: pytest.fail("must not open a bare mw._connect()"),
    )
    monkeypatch.setattr(
        mw, "_run_python_module",
        lambda *_a, **_k: pytest.fail("must not shell out via _run_python_module"),
    )


# ---------------------------------------------------------------------------
# resolve_context — item/project reads relay
# ---------------------------------------------------------------------------
class TestResolveContextRelays:
    def test_yoke_project_relays_item_detail_get(self, monkeypatch, tmp_path):
        calls = []

        def fake(**kwargs):
            calls.append(kwargs)
            if kwargs["function_id"] == "items.detail.get":
                return _resp(
                    "items.detail.get",
                    {"item": {"id": 4242, "project": {"slug": "yoke"}}},
                )
            return _resp(kwargs["function_id"])

        monkeypatch.setattr(prep, "call_dispatcher", fake)
        monkeypatch.setattr(
            "yoke_core.domain.worktree.resolve_main_root", lambda: str(tmp_path)
        )
        monkeypatch.setattr(prep, "_find_worktree", lambda b, r: str(tmp_path))
        _no_bare_db(monkeypatch)

        # Standalone item branch: the permission the real merge boundary holds.
        ctx = prep.resolve_context(
            MergeArgs(branch="YOK-4242", standalone=True)
        )

        # The branch carries a public ref, which the dispatcher resolves to
        # the internal id server-side; the project read then targets that
        # resolved id.
        assert [c["function_id"] for c in calls] == [
            "items.detail.get", "items.detail.get",
        ]
        assert calls[0]["target"].kind == "item"
        assert calls[0]["target"].item_ref == "YOK-4242"
        assert calls[0]["target"].item_id is None
        assert calls[1]["target"].item_id == 4242
        assert ctx.project == "yoke"
        # A yoke project keeps the main checkout as repo root.
        assert ctx.repo_root == str(tmp_path)

    def test_nonyoke_project_relays_checkout_and_default_branch(
        self, monkeypatch, tmp_path
    ):
        def fake(**kwargs):
            fid = kwargs["function_id"]
            if fid == "items.detail.get":
                return _resp(
                    "items.detail.get",
                    {"item": {"id": 4243, "project": {"slug": "acme"}}},
                )
            if fid == "projects.get":
                assert kwargs["payload"]["field"] == "default_branch"
                return _resp("projects.get", {"value": "trunk"})
            return _resp(fid)

        monkeypatch.setattr(prep, "call_dispatcher", fake)
        monkeypatch.setattr(
            "yoke_core.domain.worktree.resolve_main_root", lambda: str(tmp_path)
        )
        monkeypatch.setattr(prep, "_find_worktree", lambda b, r: str(tmp_path))
        monkeypatch.setattr(
            "yoke_core.domain.project_checkout_locations.checkout_for_project_slug",
            lambda slug, **_k: Path("/checkouts/acme"),
        )
        _no_bare_db(monkeypatch)

        args = MergeArgs(branch="YOK-4243", target="main", standalone=True)
        ctx = prep.resolve_context(args)

        assert ctx.project == "acme"
        assert ctx.repo_root == "/checkouts/acme"
        assert args.target == "trunk"

    def test_epic_ref_resolution_relays_item_detail_get(self, monkeypatch, tmp_path):
        seen = []

        def fake(**kwargs):
            target = kwargs["target"]
            seen.append(
                (kwargs["function_id"], target.item_ref, target.item_id)
            )
            if kwargs["function_id"] == "items.detail.get":
                # The dispatcher resolves a public ref to its internal id
                # server-side; an id-targeted read echoes the same id back.
                if target.item_ref:
                    resolved = int(str(target.item_ref).rsplit("-", 1)[-1])
                else:
                    resolved = target.item_id
                return _resp("items.detail.get", {"item": {
                    "id": resolved,
                    "project": {"slug": "yoke"},
                }})
            return _resp(kwargs["function_id"])

        monkeypatch.setattr(prep, "call_dispatcher", fake)
        monkeypatch.setattr(
            "yoke_core.domain.worktree.resolve_main_root", lambda: str(tmp_path)
        )
        monkeypatch.setattr(prep, "_find_worktree", lambda b, r: str(tmp_path))
        _no_bare_db(monkeypatch)

        ctx = prep.resolve_context(MergeArgs(branch="YOK-4244", epic_ref="YOK-880"))

        # Epic-ref canonicalization relays a detail read carrying the public
        # epic ref, never a locally parsed id.
        assert ("items.detail.get", "YOK-880", None) in seen
        assert ctx.epic_id == "880"


# preflight_checks — PF-3..PF-6 relay
def _clean_git(args, *, cwd=None, capture=False, check=False):
    # rev-parse returns non-zero so PF-2 skips the branch-tracking check;
    # diff / ls-files return empty so PF-1 sees a clean worktree.
    if args[:1] == ["rev-parse"]:
        return SimpleNamespace(stdout="", returncode=1)
    return SimpleNamespace(stdout="", returncode=0)


def _pass_responses():
    return {
        "merge.preflight.epic_task_statuses": _resp(
            "merge.preflight.epic_task_statuses",
            {"tasks": [{"task_num": 1, "status": "done"}]},
        ),
        "workflow_item.epic_task.simulation_get": _resp(
            "workflow_item.epic_task.simulation_get",
            {"body": "42|42|integration|CLEAN|body|ts"},
        ),
        "merge.preflight.dependency_gate": _resp(
            "merge.preflight.dependency_gate",
            {"is_blocked": False, "unsatisfied_blockers": []},
        ),
        "merge.preflight.blocked_gate": _resp(
            "merge.preflight.blocked_gate",
            {"applicable": True, "item_id": TEST_ITEM_ID, "item_ref": TEST_ITEM_REF, "blocked": False},
        ),
    }


def _run_preflight(monkeypatch, responses, *, skip_simulation=False, item_id=None):
    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        return responses[kwargs["function_id"]]

    monkeypatch.setattr(pf, "call_dispatcher", fake)
    monkeypatch.setattr(pf, "item_ref_for_id", lambda _id: pytest.fail("fallback"))
    monkeypatch.setattr(mw, "_run_git", _clean_git)
    _no_bare_db(monkeypatch)

    args = MergeArgs(branch=TEST_ITEM_REF, skip_simulation=skip_simulation)
    ctx = MergeContext(
        args=args, worktree_path="/tmp/wt", epic_id="42", item_id=item_id
    )
    result = pf.preflight_checks(ctx)
    return result, calls


class TestPreflightRelays:
    def test_all_gates_pass_relays_every_function_id(self, monkeypatch, capsys):
        result, calls = _run_preflight(monkeypatch, _pass_responses())
        assert result is None  # preflight passed
        called = {c["function_id"] for c in calls}
        assert called == {
            "merge.preflight.epic_task_statuses",
            "workflow_item.epic_task.simulation_get",
            "merge.preflight.dependency_gate",
            "merge.preflight.blocked_gate",
        }

    def test_incomplete_tasks_block(self, monkeypatch, capsys):
        responses = _pass_responses()
        responses["merge.preflight.epic_task_statuses"] = _resp(
            "merge.preflight.epic_task_statuses",
            {"tasks": [{"task_num": 3, "status": "implementing"}]},
        )
        result, _ = _run_preflight(monkeypatch, responses)
        assert result is not None
        assert "FAIL: Incomplete tasks found" in capsys.readouterr().err

    def test_missing_simulation_blocks(self, monkeypatch, capsys):
        responses = _pass_responses()
        responses["workflow_item.epic_task.simulation_get"] = _resp(
            "workflow_item.epic_task.simulation_get", success=False
        )
        result, _ = _run_preflight(monkeypatch, responses)
        assert result is not None
        assert "FAIL: Integration simulation report not found" in capsys.readouterr().err

    def test_missing_simulation_overridden_by_skip(self, monkeypatch, capsys):
        responses = _pass_responses()
        responses["workflow_item.epic_task.simulation_get"] = _resp(
            "workflow_item.epic_task.simulation_get", success=False
        )
        result, _ = _run_preflight(monkeypatch, responses, skip_simulation=True)
        assert result is None
        assert "overridden (--skip-simulation)" in capsys.readouterr().err

    def test_dependency_gate_block(self, monkeypatch, capsys):
        responses = _pass_responses()
        responses["merge.preflight.dependency_gate"] = _resp(
            "merge.preflight.dependency_gate",
            {
                "is_blocked": True,
                "unsatisfied_blockers": [
                    {
                        "blocking_item": "YOK-77",
                        "blocking_status": "implementing",
                        "rationale": "must land first",
                    }
                ],
            },
        )
        result, _ = _run_preflight(monkeypatch, responses)
        assert result is not None
        err = capsys.readouterr().err
        assert "FAIL: Integration dependency gate blocked" in err
        assert "YOK-77" in err and "must land first" in err

    @pytest.mark.parametrize(("item_id", "blocked"), [(None, False), (42, True)])
    def test_dependency_gate_unavailable_respects_item_authority(
        self, monkeypatch, capsys, item_id, blocked
    ):
        responses = _pass_responses()
        responses["merge.preflight.dependency_gate"] = _resp(
            "merge.preflight.dependency_gate", success=False
        )
        result, calls = _run_preflight(
            monkeypatch, responses, item_id=item_id
        )
        assert (result is not None) is blocked
        dep_call = next(c for c in calls if c["function_id"].endswith("dependency_gate"))
        assert dep_call["target"].kind == ("item" if item_id else "global")

    def test_blocked_flag_blocks(self, monkeypatch, capsys):
        responses = _pass_responses()
        responses["merge.preflight.blocked_gate"] = _resp(
            "merge.preflight.blocked_gate",
            {
                "applicable": True,
                "item_id": TEST_ITEM_ID,
                "item_ref": TEST_ITEM_REF,
                "blocked": True,
                "reason": "upstream unresolved",
            },
        )
        result, _ = _run_preflight(monkeypatch, responses)
        assert result is not None
        err = capsys.readouterr().err
        assert f"FAIL: Item {TEST_ITEM_REF} is blocked (items.blocked=1)." in err
        assert "Reason: upstream unresolved" in err
        assert f"Run /yoke unblock {TEST_ITEM_REF} before merging." in err

    def test_blocked_gate_not_applicable_is_silent(self, monkeypatch, capsys):
        responses = _pass_responses()
        responses["merge.preflight.blocked_gate"] = _resp(
            "merge.preflight.blocked_gate", {"applicable": False}
        )
        result, _ = _run_preflight(monkeypatch, responses)
        assert result is None
        out = capsys.readouterr().out
        assert "Item not blocked" not in out
        assert "Blocked-flag gate skipped" not in out


# ---------------------------------------------------------------------------
# extract_generated_files — epic body read relays
# ---------------------------------------------------------------------------
class TestExtractGeneratedFilesRelays:
    def test_relays_item_detail_get_and_parses_body(self, monkeypatch):
        body = (
            f"## Worktree: {TEST_ITEM_REF}\n"
            "### Generated files\n"
            "- gen/a.py\n"
            "- gen/b.py\n"
            "## Worktree: YOK-99\n"
            "- gen/other.py\n"
        )

        def fake(**kwargs):
            assert kwargs["function_id"] == "items.get.run"
            assert kwargs["target"].item_id == 42
            assert kwargs["payload"]["fields"] == ["body"]
            return _resp("items.get.run", {"item_id": 42, "fields": {"body": body}})

        monkeypatch.setattr(st, "call_dispatcher", fake)
        _no_bare_db(monkeypatch)

        ctx = MergeContext(args=MergeArgs(branch=TEST_ITEM_REF), epic_id="42")
        assert st.extract_generated_files(ctx) == ["gen/a.py", "gen/b.py"]

    def test_relay_refused_returns_empty(self, monkeypatch):
        monkeypatch.setattr(
            st, "call_dispatcher",
            lambda **_k: _resp("items.get.run", success=False),
        )
        _no_bare_db(monkeypatch)
        ctx = MergeContext(args=MergeArgs(branch=TEST_ITEM_REF), epic_id="42")
        assert st.extract_generated_files(ctx) == []
