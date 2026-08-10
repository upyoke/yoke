"""Merge-boundary selection: capability probe and outcome adapter."""

from types import SimpleNamespace

from yoke_core.domain import merge_queue_route_selection as selection_mod
from yoke_core.domain.merge_queue_route import QueueLandingOutcome
from yoke_core.domain.standalone_item_merge import StandaloneMergeOutcome


def _ok_response(result):
    return SimpleNamespace(success=True, result=result, error=None)


def _fail_response(message):
    return SimpleNamespace(
        success=False, result=None, error=SimpleNamespace(message=message)
    )

def _probe_dispatch(count):
    def dispatch(*, function_id, target, payload, **_kw):
        assert function_id == "db.read.run"
        assert "merge_queue" in payload["sql"]
        return _ok_response({"rows": [[count]]})

    return dispatch


def test_probe_reads_declaration_via_registered_read():
    declared, err = selection_mod.project_declares_merge_queue(
        "yoke", dispatch=_probe_dispatch(1)
    )
    assert declared and err is None
    declared, err = selection_mod.project_declares_merge_queue(
        "yoke", dispatch=_probe_dispatch(0)
    )
    assert not declared and err is None


def test_probe_error_is_surfaced_not_swallowed():
    def dispatch(**_kw):
        return _fail_response("relay unavailable")

    declared, err = selection_mod.project_declares_merge_queue(
        "yoke", dispatch=dispatch
    )
    assert not declared
    assert "relay unavailable" in err


def test_selection_refuses_on_probe_error(monkeypatch):
    monkeypatch.setattr(
        selection_mod, "project_declares_merge_queue",
        lambda project, dispatch=None: (False, "relay unavailable"),
    )
    outcome = selection_mod.route_standalone_landing(
        item_id=1, branch="YOK-200", target="main",
        repo_root="/tmp/repo", project="yoke",
    )
    assert not outcome.ok
    assert "capability probe failed" in outcome.error


def test_selection_undeclared_uses_standalone_engine(monkeypatch):
    monkeypatch.setattr(
        selection_mod, "project_declares_merge_queue",
        lambda project, dispatch=None: (False, None),
    )
    calls = {}

    def fake_standalone(**kwargs):
        calls.update(kwargs)
        return StandaloneMergeOutcome(
            ok=True, exit_code=0, already_merged=False
        )

    monkeypatch.setattr(
        selection_mod, "merge_standalone_branch", fake_standalone
    )
    outcome = selection_mod.route_standalone_landing(
        item_id=1, branch="YOK-200", target="main",
        repo_root="/tmp/repo", project="side",
    )
    assert outcome.ok
    assert calls["branch"] == "YOK-200"
    assert calls["local_merge"] is True


def test_selection_declared_adapts_queue_outcome(monkeypatch):
    monkeypatch.setattr(
        selection_mod, "project_declares_merge_queue",
        lambda project, dispatch=None: (True, None),
    )
    seen: dict = {}

    def land(ctx, **kwargs):
        seen.update(kwargs)
        return QueueLandingOutcome(
            ok=True, exit_code=0, pr_num="42",
            commit_sha=kwargs["commit_sha"], merge_sha="m" * 40,
            warnings=("observed",),
        )

    monkeypatch.setattr(selection_mod, "land_item_through_merge_queue", land)

    def forbidden(**_kw):
        raise AssertionError("standalone engine must not run when declared")

    monkeypatch.setattr(selection_mod, "merge_standalone_branch", forbidden)
    outcome = selection_mod.route_standalone_landing(
        item_id=1, branch="YOK-200", target="main", commit_sha="c" * 40,
        repo_root="/tmp/repo", project="yoke", item_ref="YOK-200",
    )
    assert isinstance(outcome, StandaloneMergeOutcome)
    assert outcome.ok
    assert outcome.merge_sha == "m" * 40
    assert outcome.warnings == ("observed",)
    # The lane head has to survive the adaptation: evidence records it and the
    # terminal ancestry check reads it, so dropping it strands the close-out.
    assert seen["commit_sha"] == "c" * 40
    assert outcome.commit_sha == "c" * 40
