"""Planning-phase carve-out for the Bash path-claim guard.

Planning sessions writing under helper-resolved dispatch-inputs scratch no
longer hit the ``worktree-unresolved`` denial; implementation sessions and
non-scratch planning writes remain gated.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import project_scratch_dir as scratch
from yoke_core.domain import path_claim_bash_parser_planning_phase as widener
from yoke_core.domain.path_claim_bash_parser import Mutation, extract_mutations
from yoke_core.domain.path_claim_bash_parser_planning_phase import (
    drop_planning_scratch_mutations,
    is_planning_scratch_path,
    session_is_planning_phase,
)
from yoke_core.domain.path_claim_bash_guard_planning_phase_test_helpers import (
    RETIRED_DISPATCH_ROOT,
    SCRATCH_ROOT,
    _dispatch_target,
    _seed,
)

pytest_plugins = ("runtime.api.domain.path_claim_bash_guard_planning_phase_fixture",)


# ---- Path classifier ----


def test_classifier_matches_helper_dispatch_subtree(widener_db):
    target = _dispatch_target(
        item_id=1844,
        dispatch_session="abc",
        filename="spec.md",
    )
    assert is_planning_scratch_path(target, SCRATCH_ROOT)
    assert is_planning_scratch_path(
        str(scratch.dispatch_inputs_dir(create=False)), SCRATCH_ROOT
    )


def test_classifier_needs_the_client_scratch_root(widener_db):
    target = _dispatch_target(item_id=1844)
    assert not is_planning_scratch_path(target, "")
    assert not is_planning_scratch_path(target, "/elsewhere/scratch")


def test_classifier_matches_lexically_under_any_scratch_root():
    target = "/client/scratch/1/sessions/s/runs/r/dispatch-inputs/YOK-1/x/a.md"
    assert is_planning_scratch_path(target, "/client/scratch")
    assert is_planning_scratch_path(target, "/client/scratch/")
    assert not is_planning_scratch_path(
        "/client/scratch/1/sessions/s/runs/r/other/a.md", "/client/scratch"
    )


@pytest.mark.parametrize(
    "path",
    [
        "runtime/api/domain/foo.py",
        ".yoke/BOARD.md",
        f"{RETIRED_DISPATCH_ROOT}/YOK-1844/abc/attempt-1/spec.md",
        f"./{RETIRED_DISPATCH_ROOT}/YOK-1/x/attempt-1/spec.md",
        f"/Users/op/yoke/{RETIRED_DISPATCH_ROOT}/YOK-1/x/attempt-1/spec.md",
        RETIRED_DISPATCH_ROOT,
        "",
    ],
)
def test_classifier_rejects_other_paths(path, widener_db):
    assert not is_planning_scratch_path(path, SCRATCH_ROOT)


# ---- Lifecycle gate ----


@pytest.mark.parametrize(
    "workflow_id,status,expected",
    [
        ("issue", "idea", True),
        ("issue", "refining-idea", True),
        ("issue", "refined-idea", True),
        ("epic", "planning", True),
        ("epic", "plan-drafted", True),
        ("epic", "refining-plan", True),
        ("epic", "planned", True),
        ("issue", "implementing", False),
        ("issue", "reviewing-implementation", False),
        ("issue", "polishing-implementation", False),
        ("issue", "implemented", False),
        ("issue", "done", False),
    ],
)
def test_session_is_planning_phase_matrix(
    widener_db,
    workflow_id,
    status,
    expected,
):
    sid = f"sess-{workflow_id}-{status}"
    _seed(
        widener_db,
        session_id=sid,
        item_id=hash(sid) % 10000,
        status=status,
        workflow_id=workflow_id,
    )
    assert session_is_planning_phase(session_id=sid) is expected


def test_session_planning_phase_blank_session_id_returns_false(widener_db):
    assert not session_is_planning_phase(session_id="")
    assert not session_is_planning_phase(session_id=None)


def test_session_planning_phase_orphan_current_item_returns_false(widener_db):
    widener_db.execute(
        "INSERT INTO harness_sessions(session_id,current_item_id) VALUES('orphan',NULL)"
    )
    widener_db.commit()
    assert not session_is_planning_phase(session_id="orphan")


# ---- Mutation filter ----


def test_filter_drops_only_scratch_when_planning(widener_db):
    sid = "sess-shep"
    _seed(widener_db, session_id=sid, item_id=1844, status="refined-idea")
    muts = [
        Mutation(verb="redirect", target_path=_dispatch_target(item_id=1844)),
        Mutation(verb="rm", target_path="runtime/api/domain/foo.py"),
    ]
    out = drop_planning_scratch_mutations(
        muts, session_id=sid, scratch_root=SCRATCH_ROOT
    )
    assert [m.target_path for m in out] == ["runtime/api/domain/foo.py"]


def test_filter_passthrough_for_implementation_phase(widener_db):
    sid = "sess-eng"
    _seed(widener_db, session_id=sid, item_id=99, status="implementing")
    muts = [Mutation(verb="redirect", target_path=_dispatch_target(item_id=99))]
    out = drop_planning_scratch_mutations(
        muts, session_id=sid, scratch_root=SCRATCH_ROOT
    )
    assert len(out) == 1


def test_filter_preserves_ambiguous_and_suppressed_sentinels(widener_db):
    sid = "sess-plan"
    _seed(widener_db, session_id=sid, item_id=5, status="refining-idea")
    muts = [
        Mutation(verb="ambiguous", target_path="eval 'rm runtime/x.py'"),
        Mutation(verb="suppressed", target_path="# lint:no-worktree-path-check"),
        Mutation(verb="redirect", target_path=_dispatch_target(item_id=5)),
    ]
    out = drop_planning_scratch_mutations(
        muts, session_id=sid, scratch_root=SCRATCH_ROOT
    )
    assert {m.verb for m in out} == {"ambiguous", "suppressed"}


def test_filter_no_session_id_no_widening(widener_db):
    muts = [Mutation(verb="redirect", target_path=_dispatch_target(item_id=1))]
    out = drop_planning_scratch_mutations(
        muts, session_id="", scratch_root=SCRATCH_ROOT
    )
    assert len(out) == 1


def test_filter_ignores_ambient_session_env(widener_db, monkeypatch):
    sid = "sess-env"
    _seed(
        widener_db,
        session_id=sid,
        item_id=7,
        status="planning",
        workflow_id="epic",
    )
    monkeypatch.setenv("YOKE_SESSION_ID", sid)
    muts = [Mutation(verb="redirect", target_path=_dispatch_target(item_id=7))]
    out = drop_planning_scratch_mutations(
        muts, session_id="", scratch_root=SCRATCH_ROOT
    )
    assert out == muts


def test_filter_without_client_scratch_root_no_widening(widener_db):
    sid = "sess-no-root"
    _seed(widener_db, session_id=sid, item_id=8, status="refined-idea")
    muts = [Mutation(verb="redirect", target_path=_dispatch_target(item_id=8))]
    out = drop_planning_scratch_mutations(muts, session_id=sid, scratch_root="")
    assert out == muts


def test_filter_does_not_widen_retired_data_sessions_path(widener_db):
    sid = "sess-retired-root"
    _seed(widener_db, session_id=sid, item_id=1844, status="refined-idea")
    muts = [
        Mutation(
            verb="redirect",
            target_path=f"{RETIRED_DISPATCH_ROOT}/YOK-1844/x/a-1/s.md",
        )
    ]
    out = drop_planning_scratch_mutations(
        muts, session_id=sid, scratch_root=SCRATCH_ROOT
    )
    assert out == muts


# ---- extract_mutations stays pure ----


@pytest.mark.parametrize("status", ["refined-idea", "implementing"])
def test_extract_mutations_keeps_scratch_redirects(widener_db, monkeypatch, status):
    sid = f"sess-e2e-{status}"
    _seed(widener_db, session_id=sid, item_id=1844, status=status)
    monkeypatch.setenv("YOKE_SESSION_ID", sid)
    cmd = f"printf '%s' \"$body\" > {_dispatch_target(item_id=1844)}"
    muts = extract_mutations(cmd)
    assert len(muts) == 1 and muts[0].verb == "redirect"


# ---- Public surface ----


def test_widener_public_surface_complete():
    assert set(widener.__all__) == {
        "is_planning_scratch_path",
        "session_is_planning_phase",
        "drop_planning_scratch_mutations",
    }
