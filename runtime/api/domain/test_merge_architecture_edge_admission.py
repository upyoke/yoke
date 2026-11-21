"""The merge gate refuses new forbidden edges and a growing baseline."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from runtime.api.domain.architecture_edge_test_support import (
    SRC,
    commit,
    dispatch_returning,
    git,
    init_repo,
    model_response,
)
from yoke_core.domain import merge_queue_route_selection as selection
from yoke_core.domain.merge_architecture_edge_admission import (
    GATE,
    architecture_edge_refusal,
)
from yoke_core.domain.architecture_tree_scan import BASELINE_PATH

LOW, HIGH = f"{SRC}/low", f"{SRC}/high"
GRANDFATHERED = {
    "path": f"{LOW}/old.py", "imported_module": "yoke_core.high",
    "source_layer": "low", "imported_layer": "high",
}


def baseline(*rows):
    return "[\n" + ",\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n]\n"


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    init_repo(root, {
        f"{LOW}/a.py": "import json\n",
        f"{LOW}/old.py": "from yoke_core.high import b\n",
        f"{HIGH}/b.py": "from yoke_core.low import a\n",
        BASELINE_PATH: baseline(GRANDFATHERED),
    })
    git(root, "checkout", "-q", "-b", "lane")
    return root


def refusal(repo, head, dispatch=None):
    return architecture_edge_refusal(
        item_id=7, public_ref="YOK-7", commit_sha=head, target="main",
        repo_root=str(repo), project="demo",
        dispatch=dispatch or dispatch_returning(model_response()),
    )


def test_a_new_forbidden_edge_is_refused_then_passes_once_removed(repo):
    head = commit(repo, {f"{LOW}/a.py": "import json\nfrom yoke_core.high import b\n"})
    text = refusal(repo, head)
    assert "architecture_edge_forbidden" in text
    assert f"{LOW}/a.py imports yoke_core.high (low -> high; low.forbidden_edges lists high)" in text
    assert "change the import" in text and "yoke project-structure patch" in text
    assert "Nothing has been merged" in text
    head = commit(repo, {f"{LOW}/a.py": "import json\n"})
    assert refusal(repo, head) == ""


def test_grandfathered_and_base_edges_pass_on_a_changed_file(repo):
    head = commit(repo, {
        f"{LOW}/old.py": "from yoke_core.high import b\nimport os\n",
        f"{HIGH}/b.py": "from yoke_core.low import a\nimport os\n",
    })
    assert refusal(repo, head) == ""


def test_a_renamed_file_keeps_its_frozen_edge(repo):
    git(repo, "mv", f"{LOW}/old.py", f"{LOW}/renamed.py")
    head = commit(repo, {BASELINE_PATH: baseline({**GRANDFATHERED, "path": f"{LOW}/renamed.py"})})
    assert refusal(repo, head) == ""


def test_a_baseline_that_grows_is_refused(repo):
    extra = {**GRANDFATHERED, "path": f"{LOW}/a.py"}
    head = commit(repo, {BASELINE_PATH: baseline(GRANDFATHERED, extra)})
    text = refusal(repo, head)
    assert "architecture_baseline_grew" in text
    assert f"{LOW}/a.py imports yoke_core.high (low -> high)" in text


def test_a_lane_without_a_committed_baseline_is_skipped_with_a_note(tmp_path, capsys):
    root = tmp_path / "plain"
    head = init_repo(root, {f"{LOW}/a.py": "from yoke_core.high import b\n", f"{HIGH}/b.py": ""})
    calls = []
    assert refusal(root, head, dispatch_returning(model_response(), calls)) == ""
    assert calls == []
    assert f"commits no {BASELINE_PATH}; skipped" in capsys.readouterr().err


def test_a_project_without_a_model_is_skipped_with_a_note(repo, capsys):
    head = commit(repo, {f"{LOW}/a.py": "from yoke_core.high import b\n"})
    assert refusal(repo, head, dispatch_returning(model_response(None))) == ""
    assert "declares no architecture_model; skipped" in capsys.readouterr().err


def test_an_unreadable_model_refuses(repo):
    head = commit(repo, {f"{LOW}/a.py": "import os\n"})
    response = model_response(success=False, code="permission_denied", message="no read")
    text = refusal(repo, head, dispatch_returning(response))
    assert "architecture_model_unreadable: demo: no read" in text


@pytest.mark.parametrize("code", ["function_not_registered", "function_version_skew"])
def test_an_unserved_model_read_proceeds_with_a_note(repo, capsys, code):
    head = commit(repo, {f"{LOW}/a.py": "from yoke_core.high import b\n"})
    response = model_response(success=False, code=code)
    assert refusal(repo, head, dispatch_returning(response)) == ""
    assert f"not served ({code})" in capsys.readouterr().err


def test_route_admission_names_the_gate_after_candidate_review(repo, monkeypatch):
    head = commit(repo, {f"{LOW}/a.py": "from yoke_core.high import b\n"})
    monkeypatch.setattr(selection, "integration_dependency_refusal", lambda **_k: "")
    monkeypatch.setattr(selection, "candidate_review_refusal", lambda **_k: "")
    admission = selection.route_admission(
        item_id=7, branch="lane", target="main", repo_root=str(repo), project="demo",
        public_ref="YOK-7", dispatch=dispatch_returning(model_response()),
    )
    assert admission.gate == GATE
    assert admission.review_head == head
    assert "architecture_edge_forbidden" in admission.refusal


def test_epic_preflight_fails_on_the_gate(monkeypatch, capsys):
    from yoke_core.domain import merge_architecture_edge_admission as gate_mod
    from yoke_core.engines import merge_worktree as mw
    from yoke_core.engines import merge_worktree_prepare_preflight as pf
    from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext

    def fake_git(args, *, cwd=None, capture=False, check=False):
        if args == ["rev-parse", "HEAD"]:
            return SimpleNamespace(stdout="f" * 40 + "\n", returncode=0)
        return SimpleNamespace(stdout="", returncode=1 if args[0] == "rev-parse" else 0)

    seen = {}

    def gate(**kwargs):
        seen.update(kwargs)
        return "architecture_edge_forbidden: planted"

    monkeypatch.setattr(mw, "_run_git", fake_git)
    monkeypatch.setattr(gate_mod, "architecture_edge_refusal", gate)
    monkeypatch.setattr(
        "yoke_core.engines.merge_task_completeness.task_completion_failure", lambda _e: ""
    )
    monkeypatch.setattr(pf, "call_dispatcher", lambda **_k: SimpleNamespace(
        success=True, result={"body": "report", "is_blocked": False,
                              "applicable": False}, error=None))
    ctx = MergeContext(args=MergeArgs(branch="YOK-9"), worktree_path="/tmp/wt",
                       repo_root="/tmp/repo", epic_id="YOK-9", project="demo")
    assert pf.preflight_checks(ctx) is not None
    assert seen["commit_sha"] == "f" * 40 and seen["project"] == "demo"
    assert "FAIL: architecture_edge_forbidden: planted" in capsys.readouterr().err
