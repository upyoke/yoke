"""HC-worktree-health runs wherever the checkout is, over any transport.

The check used to read its control-plane half with local SQL, so on an
https client — which holds the checkout but has no local database — it
could only ever report N/A, and released lanes for hosted and external
projects accumulated unseen. These tests drive the check with exactly that
runtime: ``UnavailableControlPlane`` as the connection, and the relayed
reads standing in for the control plane.
"""

from __future__ import annotations

import subprocess
from typing import Any, Dict, List

import pytest

from yoke_core.engines import doctor_hc_worktrees_health as hc
from yoke_core.engines import doctor_worktree_lane_authority as lane_authority
from yoke_core.engines.doctor_https_compose import UnavailableControlPlane
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_LANE = {
    "item_id": 70,
    "public_ref": "PLAT-139",
    "status": "done",
    "branch": "PLAT-139",
    "path": "/repo/.worktrees/PLAT-139",
    "state": "released",
    "target_branch": "main",
}

_PORCELAIN = (
    "worktree /repo\nbranch refs/heads/main\n\n"
    "worktree /repo/.worktrees/PLAT-139\nbranch refs/heads/PLAT-139\n\n"
)


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["git"], returncode=returncode, stdout=stdout, stderr=""
    )


class _Assessment:
    def __init__(self, safe: bool, reason: str = "") -> None:
        self.safe = safe
        self.reason = reason


class _Residue:
    """A lane holding nothing but disposable generated state."""

    disposable = True
    precious_paths: tuple[str, ...] = ()
    reason = ""


@pytest.fixture
def relayed_client(monkeypatch):
    """An https-style client: a checkout on disk, no local database."""
    calls: Dict[str, List[Any]] = {"relay": [], "prune": []}

    def fake_run(cmd, *_a, **_kw):
        if cmd[:3] == ["git", "worktree", "list"]:
            return _completed(_PORCELAIN)
        if cmd[:2] == ["git", "for-each-ref"]:
            return _completed("PLAT-139\n")
        return _completed("", returncode=1)

    monkeypatch.setattr(hc._base, "_run", fake_run)
    monkeypatch.setattr(hc._base, "_resolve_repo_root", lambda: "/repo")
    monkeypatch.setattr(hc, "declared_disposable_roots", lambda _root: frozenset())
    monkeypatch.setattr(hc, "assess_lane_residue", lambda *_a, **_kw: _Residue())
    monkeypatch.setattr(
        hc.Path, "is_dir", lambda self: str(self) == "/repo/.worktrees/PLAT-139"
    )
    monkeypatch.setattr(hc, "assess_landed_lane", lambda **_kw: _Assessment(safe=True))

    def fake_prune(**kwargs):
        calls["prune"].append(kwargs)
        return ()

    monkeypatch.setattr(hc, "prune_landed_lane", fake_prune)
    return calls


def _install_relay(monkeypatch, calls, *, inventory, verdict):
    def fake_relay(function_id: str, payload: dict, *_a, **_kw):
        calls["relay"].append((function_id, payload))
        if function_id == "item_worktrees.inventory":
            if isinstance(inventory, Exception):
                raise inventory
            return inventory
        if function_id == "merge.prune.authority_verdict":
            if isinstance(verdict, Exception):
                raise verdict
            return verdict
        raise AssertionError(f"unexpected relayed function {function_id}")

    monkeypatch.setattr(lane_authority, "relay", fake_relay)


def _run_check(args: DoctorArgs) -> RecordCollector:
    rec = RecordCollector()
    hc.hc_worktree_health(UnavailableControlPlane(), args, rec)
    return rec


def test_check_runs_against_an_https_client_with_a_checkout(
    monkeypatch, relayed_client
) -> None:
    """No local database, yet the check reaches a real verdict."""
    _install_relay(
        monkeypatch,
        relayed_client,
        inventory={"lanes": [_LANE]},
        verdict={"prunable": True, "reason": "prunable"},
    )

    rec = _run_check(DoctorArgs(project="platform"))

    [result] = rec.results
    assert result.result == "WARN"
    assert "PLAT-139" in result.detail
    assert "sweep-ready" in result.detail
    # The control-plane half came from the relay, never from a connection.
    assert ("item_worktrees.inventory", {"project": "platform"}) in relayed_client[
        "relay"
    ]


def test_missing_repo_root_uses_each_lanes_disposable_declarations(
    monkeypatch, relayed_client
):
    from pathlib import PurePosixPath

    _install_relay(monkeypatch, relayed_client, inventory={"lanes": []}, verdict={})
    monkeypatch.setattr(hc._base, "_resolve_repo_root", lambda: None)
    roots = frozenset({PurePosixPath(".generated")})
    observed = []

    def declared(root):
        observed.append(root)
        return roots

    def residue(run_git, path, actual_roots):
        assert actual_roots == roots
        return _Residue()

    monkeypatch.setattr(hc, "declared_disposable_roots", declared)
    monkeypatch.setattr(hc, "assess_lane_residue", residue)
    rec = _run_check(DoctorArgs(project="platform"))
    assert observed == ["/repo"]
    assert [row.result for row in rec.results] == ["PASS"]


def test_fix_retires_a_disposable_terminal_lane_over_https(
    monkeypatch, relayed_client
) -> None:
    _install_relay(
        monkeypatch,
        relayed_client,
        inventory={"lanes": [_LANE]},
        verdict={"prunable": True, "reason": "prunable"},
    )

    rec = _run_check(DoctorArgs(project="platform", fix=True))

    [result] = rec.results
    assert "Fixed: removed terminal lane PLAT-139" in result.detail
    assert relayed_client["prune"], "the lane should have been pruned"
    assert relayed_client["prune"][0]["branch"] == "PLAT-139"
    assert relayed_client["prune"][0]["item_id"] == 70


def test_unservable_inventory_is_not_applicable_never_a_pass(
    monkeypatch, relayed_client
) -> None:
    """A control plane that cannot answer must not read as a clean bill."""
    _install_relay(
        monkeypatch,
        relayed_client,
        inventory=RuntimeError("engine does not serve item_worktrees.inventory"),
        verdict={"prunable": True, "reason": "prunable"},
    )

    rec = _run_check(DoctorArgs(project="platform", fix=True))

    [result] = rec.results
    assert result.result == "N/A"
    assert "item_worktrees.inventory" in result.detail
    assert not relayed_client["prune"], "nothing may be pruned on an unproven read"


def test_active_authority_preserves_the_lane(monkeypatch, relayed_client) -> None:
    """A live holder keeps its lane even with --fix."""
    monkeypatch.setattr(
        hc,
        "assess_landed_lane",
        lambda **kw: _Assessment(
            safe=not kw.get("authority_block"),
            reason=f"preserved: {kw.get('authority_block')}",
        ),
    )
    _install_relay(
        monkeypatch,
        relayed_client,
        inventory={"lanes": [_LANE]},
        verdict={"prunable": False, "reason": "active_authority"},
    )

    rec = _run_check(DoctorArgs(project="platform", fix=True))

    [result] = rec.results
    assert "claimed" in result.detail
    assert not relayed_client["prune"]


def test_unreachable_authority_fails_closed(monkeypatch, relayed_client) -> None:
    """An unreadable verdict preserves rather than prunes."""
    monkeypatch.setattr(
        hc,
        "assess_landed_lane",
        lambda **kw: _Assessment(
            safe=not kw.get("authority_block"),
            reason=f"preserved: {kw.get('authority_block')}",
        ),
    )
    _install_relay(
        monkeypatch,
        relayed_client,
        inventory={"lanes": [_LANE]},
        verdict=RuntimeError("control plane unreachable"),
    )

    _run_check(DoctorArgs(project="platform", fix=True))

    assert not relayed_client["prune"]


def test_historical_lane_count_does_not_launch_one_git_read_per_row(
    monkeypatch, relayed_client
):
    lanes = [
        dict(_LANE, branch=f"old-{i}", path=f"/repo/.worktrees/old-{i}")
        for i in range(1000)
    ]
    _install_relay(
        monkeypatch,
        relayed_client,
        inventory={"lanes": lanes},
        verdict={"prunable": True},
    )
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        normalized = ["git", *cmd[3:]] if cmd[:2] == ["git", "-C"] else cmd
        if normalized[:3] == ["git", "worktree", "list"]:
            return _completed("worktree /repo\nbranch refs/heads/main\n\n")
        if cmd[:2] == ["git", "for-each-ref"]:
            return _completed("main\n")
        raise AssertionError(cmd)

    monkeypatch.setattr(hc._base, "_run", run)
    assert _run_check(DoctorArgs(project="platform")).results[0].result == "PASS"
    assert len(calls) <= 3
