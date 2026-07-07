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
    PLANNING_SCRATCH_ROOTS,
    drop_planning_scratch_mutations,
    is_planning_scratch_path,
    planning_scratch_roots,
    session_is_planning_phase,
)
from yoke_core.domain.path_claim_bash_guard_planning_phase_test_helpers import (
    RETIRED_DISPATCH_ROOT,
    _dispatch_target,
    _seed,
    widener_db,
)


# ---- Path classifier ----

def test_classifier_matches_helper_dispatch_subtree(widener_db, monkeypatch):
    monkeypatch.setenv("YOKE_SESSION_ID", "sess-classifier")
    target = _dispatch_target(
        item_id=1844,
        dispatch_session="abc",
        filename="spec.md",
    )
    assert is_planning_scratch_path(target)
    assert is_planning_scratch_path(str(scratch.dispatch_inputs_dir(create=False)))


@pytest.mark.parametrize("path", [
    "runtime/api/domain/foo.py", ".yoke/BOARD.md",
    f"{RETIRED_DISPATCH_ROOT}/YOK-1844/abc/attempt-1/spec.md",
    f"./{RETIRED_DISPATCH_ROOT}/YOK-1/x/attempt-1/spec.md",
    f"/Users/op/yoke/{RETIRED_DISPATCH_ROOT}/YOK-1/x/attempt-1/spec.md",
    RETIRED_DISPATCH_ROOT,
    "",
])
def test_classifier_rejects_other_paths(path, widener_db):
    assert not is_planning_scratch_path(path)


def test_planning_scratch_roots_published(widener_db):
    assert PLANNING_SCRATCH_ROOTS == (
        "project_scratch_dir.dispatch_inputs_dir",
    )
    assert planning_scratch_roots() == (
        str(scratch.dispatch_inputs_dir(create=False)),
    )


# ---- Lifecycle gate ----

@pytest.mark.parametrize("status,expected", [
    ("idea", True), ("refining-idea", True), ("refined-idea", True),
    ("planning", True), ("plan-drafted", True), ("refining-plan", True),
    ("planned", True),
    ("implementing", False), ("reviewing-implementation", False),
    ("polishing-implementation", False), ("implemented", False), ("done", False),
])
def test_session_is_planning_phase_matrix(widener_db, status, expected):
    sid = f"sess-{status}"
    _seed(widener_db, session_id=sid, item_id=hash(status) % 10000, status=status)
    assert session_is_planning_phase(session_id=sid) is expected


def test_session_planning_phase_blank_session_id_returns_false(widener_db):
    assert not session_is_planning_phase(session_id="")
    assert not session_is_planning_phase(session_id=None)


def test_session_planning_phase_orphan_current_item_returns_false(widener_db):
    widener_db.execute(
        "INSERT INTO harness_sessions(session_id,current_item_id) "
        "VALUES('orphan',NULL)"
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
    out = drop_planning_scratch_mutations(muts, session_id=sid)
    assert [m.target_path for m in out] == ["runtime/api/domain/foo.py"]


def test_filter_passthrough_for_implementation_phase(widener_db):
    sid = "sess-eng"
    _seed(widener_db, session_id=sid, item_id=99, status="implementing")
    muts = [Mutation(verb="redirect",
                     target_path=_dispatch_target(item_id=99))]
    out = drop_planning_scratch_mutations(muts, session_id=sid)
    assert len(out) == 1


def test_filter_preserves_ambiguous_and_suppressed_sentinels(widener_db):
    sid = "sess-plan"
    _seed(widener_db, session_id=sid, item_id=5, status="refining-idea")
    muts = [
        Mutation(verb="ambiguous", target_path="eval 'rm runtime/x.py'"),
        Mutation(verb="suppressed", target_path="# lint:no-worktree-path-check"),
        Mutation(verb="redirect",
                 target_path=_dispatch_target(item_id=5)),
    ]
    out = drop_planning_scratch_mutations(muts, session_id=sid)
    assert {m.verb for m in out} == {"ambiguous", "suppressed"}


def test_filter_no_session_id_no_widening(widener_db):
    muts = [Mutation(verb="redirect",
                     target_path=_dispatch_target(item_id=1))]
    assert len(drop_planning_scratch_mutations(muts, session_id=None)) == 1


def test_filter_env_var_fallback(widener_db, monkeypatch):
    sid = "sess-env"
    _seed(widener_db, session_id=sid, item_id=7, status="planning")
    monkeypatch.setenv("YOKE_SESSION_ID", sid)
    muts = [Mutation(verb="redirect",
                     target_path=_dispatch_target(item_id=7))]
    assert drop_planning_scratch_mutations(muts) == []


def test_filter_does_not_widen_retired_data_sessions_path(widener_db):
    sid = "sess-retired-root"
    _seed(widener_db, session_id=sid, item_id=1844, status="refined-idea")
    muts = [Mutation(
        verb="redirect",
        target_path=f"{RETIRED_DISPATCH_ROOT}/YOK-1844/x/a-1/s.md",
    )]
    assert drop_planning_scratch_mutations(muts, session_id=sid) == muts


# ---- extract_mutations integration ----

def test_extract_mutations_filters_planning_scratch(widener_db, monkeypatch):
    sid = "sess-e2e-plan"
    _seed(widener_db, session_id=sid, item_id=1844, status="refined-idea")
    monkeypatch.setenv("YOKE_SESSION_ID", sid)
    cmd = f'printf \'%s\' "$body" > {_dispatch_target(item_id=1844)}'
    assert extract_mutations(cmd) == []


def test_extract_mutations_passes_through_for_implementing(widener_db, monkeypatch):
    sid = "sess-e2e-impl"
    _seed(widener_db, session_id=sid, item_id=2024, status="implementing")
    monkeypatch.setenv("YOKE_SESSION_ID", sid)
    cmd = f'printf \'%s\' "$body" > {_dispatch_target(item_id=2024)}'
    muts = extract_mutations(cmd)
    assert len(muts) == 1 and muts[0].verb == "redirect"


# ---- Public surface ----

def test_widener_public_surface_complete():
    for name in ("is_planning_scratch_path", "session_is_planning_phase",
                 "drop_planning_scratch_mutations", "planning_scratch_roots",
                 "PLANNING_SCRATCH_ROOTS"):
        assert name in widener.__all__
