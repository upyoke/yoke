"""The standing relay sweeps finished lanes on its own machine.

It sweeps once at start and then every interval, on a thread the poll loop
never waits for, only from the prod relay, and never beside another sweep
of the same checkout.
"""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

from runtime.api.engines._merge_prune_test_helpers import _Conn, _install, _repo
from yoke_core.domain import terminal_lane_cleanup
from yoke_core.engines.lane_sweep_lock import SWEEP_LOCK_HELD, lane_sweep_lock
from yoke_core.engines.merge_worktree_safe_prune import prune_managed_worktrees
from yoke_core.tools import session_relay_lane_sweep as relay_sweep


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _finish(sweep: relay_sweep.RelayLaneSweep) -> None:
    thread = sweep._thread
    if thread is not None:
        thread.join(timeout=5)
        assert not thread.is_alive()


def test_the_relay_sweeps_at_start_and_then_once_per_interval():
    clock, runs = _Clock(), []
    sweep = relay_sweep.RelayLaneSweep(
        interval_seconds=900, clock=clock, sweep=lambda **_kw: runs.append(clock.now)
    )

    sweep()
    _finish(sweep)
    clock.now = 899
    sweep()
    _finish(sweep)
    clock.now = 900
    sweep()
    _finish(sweep)

    assert runs == [0.0, 900]


def test_a_running_sweep_never_blocks_the_poll_or_starts_twice():
    release, started, runs = threading.Event(), threading.Event(), []

    def slow(**_kw):
        runs.append(1)
        started.set()
        assert release.wait(timeout=5)

    clock = _Clock()
    sweep = relay_sweep.RelayLaneSweep(interval_seconds=1, clock=clock, sweep=slow)

    sweep()
    assert started.wait(timeout=5)
    clock.now = 10
    sweep()  # due again, but the first sweep still holds the thread

    assert runs == [1]
    release.set()
    _finish(sweep)


def test_only_the_prod_relay_sweeps_and_a_stage_relay_says_why_once():
    runs, lines = [], []
    stage = relay_sweep.relay_lane_sweep(
        SimpleNamespace(prod=False, environment="stage")
    )
    stage._sweep = lambda **_kw: runs.append(1)
    stage._log = lines.append

    stage()
    stage()

    assert runs == []
    assert len(lines) == 1
    assert "relay env 'stage' is not the prod connection" in lines[0]
    assert relay_sweep.relay_lane_sweep(
        SimpleNamespace(prod=True, environment="prod")
    )._off_reason == ""


def test_an_unexpected_refusal_is_logged_and_the_relay_keeps_standing():
    lines: list[str] = []

    def broken(**_kw):
        raise RuntimeError("git unavailable")

    sweep = relay_sweep.RelayLaneSweep(sweep=broken, log=lines.append)
    sweep()
    _finish(sweep)

    assert lines == [
        "stopped after an unexpected refusal: git unavailable; the next "
        "sweep runs in 15 minutes"
    ]


def test_each_mapped_checkout_is_swept_against_its_default_branch(monkeypatch):
    swept, lines = [], []
    monkeypatch.setattr(
        "yoke_contracts.machine_config.runtime.load_config", lambda *_a: {}
    )
    monkeypatch.setattr(
        "yoke_contracts.machine_config.schema.mapped_checkouts",
        lambda _config: [("/work/b", 2), ("/work/a", 1)],
    )
    monkeypatch.setattr(
        relay_sweep,
        "_default_branch",
        lambda project_id: ("main", "") if project_id == 1 else ("", "refused"),
    )

    def sweep(**kwargs):
        swept.append((kwargs["repo_root"], kwargs["target"]))
        return (), {"removed": ["/work/a/.worktrees/X-1"], "preserved": []}

    monkeypatch.setattr(terminal_lane_cleanup, "sweep_managed_lanes", sweep)

    relay_sweep.sweep_mapped_checkouts(log=lines.append)

    assert swept == [("/work/a", "main")]
    assert lines == [
        "/work/a against main: removed 1, kept 0",
        "/work/b skipped: project 2 could not be read (refused); the next "
        "sweep retries it",
    ]


def test_a_sweep_finding_the_checkout_lock_held_skips(monkeypatch, tmp_path: Path):
    repo, worktree, branch = _repo(tmp_path)
    git_io, _lines = _install(monkeypatch, repo, _Conn(branch))

    with lane_sweep_lock(repo / ".git") as held:
        assert held
        sweep = prune_managed_worktrees(**git_io, repo_root=str(repo), target="main")

    assert sweep.skipped == SWEEP_LOCK_HELD
    assert worktree.exists()
    after = prune_managed_worktrees(**git_io, repo_root=str(repo), target="main")
    assert after.removed == (str(worktree.resolve()),)
