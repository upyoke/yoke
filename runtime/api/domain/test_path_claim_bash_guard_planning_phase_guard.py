"""Guard-level planning scratch coverage."""

from __future__ import annotations

from typing import Any, Dict

from yoke_core.domain import path_claim_bash_guard as bash_guard
from yoke_core.domain.path_claim_bash_guard_planning_phase_test_helpers import (
    PROJECT_REPO_ROOT,
    RETIRED_DISPATCH_ROOT,
    _dispatch_target,
    _seed,
    widener_db,
)


def _planned_no_wt_claim(item_id=1844) -> Dict[str, Any]:
    return {"id": 300, "item_id": item_id, "integration_target": "main",
            "state": "planned",
            "covered_paths": ("runtime/api/domain/foo.py",), "worktree_path": "",
            "project_repo_path": PROJECT_REPO_ROOT}


def _payload(*, command, cwd, session_id) -> Dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command},
            "cwd": cwd, "session_id": session_id}


def _patch_guard(monkeypatch, claim):
    monkeypatch.setattr(bash_guard, "resolve_active_claim_for_session",
                        lambda session_id, conn=None: claim)
    monkeypatch.setattr(bash_guard, "_emit_denial", lambda **_k: None)


def test_matrix_planning_session_scratch_allows(tmp_path, widener_db, monkeypatch):
    sid = "sess-mx-1"
    _seed(widener_db, session_id=sid, item_id=1844, status="refined-idea")
    monkeypatch.setenv("YOKE_SESSION_ID", sid)
    _patch_guard(monkeypatch, _planned_no_wt_claim())
    target = _dispatch_target(item_id=1844)
    v = bash_guard.evaluate_payload(_payload(
        command=f"printf '%s' \"$b\" > {target}", cwd=str(tmp_path), session_id=sid))
    assert v.outcome == "allow"


def test_matrix_planning_session_code_edit_denies(tmp_path, widener_db, monkeypatch):
    sid = "sess-mx-2"
    _seed(widener_db, session_id=sid, item_id=1844, status="refined-idea")
    monkeypatch.setenv("YOKE_SESSION_ID", sid)
    _patch_guard(monkeypatch, _planned_no_wt_claim())
    v = bash_guard.evaluate_payload(_payload(
        command="rm runtime/api/domain/other.py",
        cwd=str(tmp_path), session_id=sid))
    assert v.outcome == "deny"


def test_matrix_impl_session_scratch_outside_claim_denies(
    tmp_path, widener_db, monkeypatch,
):
    sid = "sess-mx-3"
    _seed(widener_db, session_id=sid, item_id=2024, status="implementing")
    monkeypatch.setenv("YOKE_SESSION_ID", sid)
    wt = tmp_path / "YOK-2024"; wt.mkdir()
    _patch_guard(monkeypatch, {
        "id": 400, "item_id": 2024, "integration_target": "main",
        "state": "active",
        "covered_paths": ("runtime/api/domain/bar.py",),
        "worktree_path": str(wt),
        "project_repo_path": PROJECT_REPO_ROOT,
    })
    target = _dispatch_target(item_id=2024)
    v = bash_guard.evaluate_payload(_payload(
        command=f"printf '%s' \"$b\" > {target}", cwd=str(wt), session_id=sid))
    assert v.outcome == "deny"


def test_matrix_impl_session_code_edit_inside_claim_allows(
    tmp_path, widener_db, monkeypatch,
):
    sid = "sess-mx-4"
    _seed(widener_db, session_id=sid, item_id=2024, status="implementing")
    monkeypatch.setenv("YOKE_SESSION_ID", sid)
    wt = tmp_path / "YOK-2024"; (wt / "runtime/api/domain").mkdir(parents=True)
    _patch_guard(monkeypatch, {
        "id": 400, "item_id": 2024, "integration_target": "main",
        "state": "active",
        "covered_paths": ("runtime/api/domain/bar.py",),
        "worktree_path": str(wt),
        "project_repo_path": PROJECT_REPO_ROOT,
    })
    v = bash_guard.evaluate_payload(_payload(
        command="rm runtime/api/domain/bar.py", cwd=str(wt), session_id=sid))
    assert v.outcome == "allow"


def test_planning_session_authors_scratch_for_unrelated_item(
    tmp_path, widener_db, monkeypatch,
):
    sid = "sess-cross"
    _seed(widener_db, session_id=sid, item_id=1848, status="refined-idea")
    monkeypatch.setenv("YOKE_SESSION_ID", sid)
    _patch_guard(monkeypatch, _planned_no_wt_claim(item_id=1848))
    target = _dispatch_target(item_id=9999)
    v = bash_guard.evaluate_payload(_payload(
        command=f"printf '%s' \"$b\" > {target}", cwd=str(tmp_path), session_id=sid))
    assert v.outcome == "allow"


def test_guard_uses_payload_session_id_without_env_var(
    tmp_path, widener_db, monkeypatch,
):
    sid = "sess-payload-only"
    _seed(widener_db, session_id=sid, item_id=1883, status="refined-idea")
    monkeypatch.delenv("YOKE_SESSION_ID", raising=False)
    _patch_guard(monkeypatch, _planned_no_wt_claim(item_id=1883))
    target = _dispatch_target(item_id=1883)
    v = bash_guard.evaluate_payload(_payload(
        command=f"printf '%s' \"$b\" > {target}", cwd=str(tmp_path), session_id=sid))
    assert v.outcome == "allow", (
        f"carve-out should fire from payload session_id alone; got {v}"
    )


def test_original_worktree_unresolved_denial_no_longer_fires(
    tmp_path, widener_db, monkeypatch,
):
    sid = "sess-repro"
    _seed(widener_db, session_id=sid, item_id=1844, status="refined-idea")
    monkeypatch.setenv("YOKE_SESSION_ID", sid)
    _patch_guard(monkeypatch, _planned_no_wt_claim())
    cmd = (
        f'printf \'%s\' "$spec" > '
        f'{_dispatch_target(item_id=1844, dispatch_session="sess", filename="product-manager-spec.md")}'
    )
    v = bash_guard.evaluate_payload(_payload(
        command=cmd, cwd=str(tmp_path), session_id=sid))
    assert v.outcome == "allow"
    assert "worktree-unresolved" not in v.narrative
    assert v.failure_mode != "worktree-unresolved"


def test_retired_data_sessions_path_hits_original_denial(
    tmp_path, widener_db, monkeypatch,
):
    sid = "sess-retired-repro"
    _seed(widener_db, session_id=sid, item_id=1844, status="refined-idea")
    monkeypatch.setenv("YOKE_SESSION_ID", sid)
    _patch_guard(monkeypatch, _planned_no_wt_claim())
    cmd = (
        'printf \'%s\' "$spec" '
        f'> {RETIRED_DISPATCH_ROOT}/YOK-1844/sess/attempt-1/'
        'product-manager-spec.md'
    )
    v = bash_guard.evaluate_payload(_payload(
        command=cmd, cwd=PROJECT_REPO_ROOT, session_id=sid))
    assert v.outcome == "deny"
    assert v.failure_mode == "worktree-unresolved"
