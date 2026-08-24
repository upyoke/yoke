"""Ref resolution, run matching, and the terminal shapes of a CI watch.

The two matching mistakes this module exists to prevent are silent: a
hash padded from an abbreviated SHA and a match against the run's display
title both leave a poll loop waiting on a set that can never match. Both
are asserted here directly, because neither shows up as a failure at
runtime — only as a watch that never ends.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_core.domain import github_actions_commit_run_watch as watch


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A one-commit repository on a known branch."""
    _git(tmp_path, "init", "--initial-branch", "main", ".")
    _git(tmp_path, "config", "user.email", "watcher@example.invalid")
    _git(tmp_path, "config", "user.name", "Watcher")
    (tmp_path / "file.txt").write_text("content\n", encoding="utf-8")
    _git(tmp_path, "add", "file.txt")
    _git(tmp_path, "commit", "-m", "initial")
    return tmp_path


class FakeClock:
    """A clock that only advances when the watch decides to wait."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _run(
    run_id: int,
    *,
    name: str = "yoke-ci",
    head_sha: str = "a" * 40,
    status: str = "in_progress",
    conclusion: str | None = None,
) -> dict:
    return {
        "id": run_id,
        "name": name,
        "head_sha": head_sha,
        "status": status,
        "conclusion": conclusion,
        "html_url": f"https://example.invalid/runs/{run_id}",
    }


def _watch(fetch, clock: FakeClock, emitted: list[str], **kwargs) -> int:
    return watch.watch_commit_runs(
        head_sha="a" * 40,
        ref="HEAD",
        repo="owner/name",
        workflow_name="",
        fetch_runs=fetch,
        emit=emitted.append,
        now=clock,
        sleep=clock.sleep,
        **kwargs,
    )


def test_every_ref_shape_resolves_to_the_same_object_id(repo: Path):
    """Branch, HEAD, and an abbreviated SHA name one commit.

    The abbreviation case is the one that matters: expanding it by any
    means other than asking git produces a hash that matches nothing.
    """
    full = _git(repo, "rev-parse", "HEAD")
    assert watch.resolve_commit("HEAD", cwd=repo) == full
    assert watch.resolve_commit("main", cwd=repo) == full
    assert watch.resolve_commit(full[:7], cwd=repo) == full
    assert len(full) == 40


def test_an_unknown_ref_is_refused_rather_than_guessed(repo: Path):
    with pytest.raises(watch.CommitResolutionError):
        watch.resolve_commit("no-such-branch", cwd=repo)


def test_a_run_for_a_neighbouring_commit_never_matches():
    """The server filters, and the module checks the filter."""
    captured: dict = {}

    def fake_get(path, *, query, token):
        captured["path"] = path
        captured["query"] = query
        return {
            "workflow_runs": [
                _run(1, head_sha="a" * 40),
                _run(2, head_sha="b" * 40),
            ]
        }

    matched = watch.matching_runs(
        "owner/name", "a" * 40, "", token="t", get=fake_get,
    )

    assert [run["id"] for run in matched] == [1]
    assert captured["query"]["head_sha"] == "a" * 40
    assert captured["path"] == "/repos/owner/name/actions/runs"


def test_the_workflow_filter_reads_the_workflow_name_not_the_run_title():
    """``name`` on a REST run is the workflow; the title is separate.

    A filter keyed on the run's display title ("yoke-ci main") never
    matches the workflow name ("yoke-ci"), and fails by waiting.
    """
    runs = [
        _run(1, name="yoke-ci"),
        _run(2, name="release"),
    ]
    titled = dict(runs[0], display_title="yoke-ci main")

    def fake_get(path, *, query, token):
        return {"workflow_runs": [titled, runs[1]]}

    matched = watch.matching_runs(
        "owner/name", "a" * 40, "yoke-ci", token="t", get=fake_get,
    )

    assert [run["id"] for run in matched] == [1]


def test_a_malformed_response_yields_no_matches_rather_than_raising():
    def fake_get(path, *, query, token):
        return {"workflow_runs": ["not-a-run", None]}

    assert watch.matching_runs(
        "owner/name", "a" * 40, "", token="t", get=fake_get,
    ) == []


@pytest.mark.parametrize(
    "conclusion", ["success", "failure", "cancelled", "timed_out"],
)
def test_every_terminal_conclusion_is_announced(conclusion: str):
    """A watch that ends without saying how is the failure mode."""
    clock = FakeClock()
    emitted: list[str] = []
    states = iter(
        [
            [_run(1, status="queued")],
            [_run(1, status="completed", conclusion=conclusion)],
        ]
    )

    code = _watch(lambda: next(states), clock, emitted)

    concluded = [line for line in emitted if line.startswith("CI run concluded:")]
    assert len(concluded) == 1
    assert conclusion in concluded[0]
    assert code == (
        watch.EXIT_SUCCESS if conclusion == "success"
        else watch.EXIT_CONCLUDED_FAILURE
    )


def test_each_state_change_emits_once_and_repeats_stay_quiet():
    clock = FakeClock()
    emitted: list[str] = []
    states = iter(
        [
            [_run(1, status="queued")],
            [_run(1, status="queued")],
            [_run(1, status="in_progress")],
            [_run(1, status="completed", conclusion="success")],
        ]
    )

    assert _watch(lambda: next(states), clock, emitted) == watch.EXIT_SUCCESS

    statuses = [line for line in emitted if line.startswith("CI run status:")]
    assert len(statuses) == 3
    assert " queued " in statuses[0]
    assert " in_progress " in statuses[1]
    assert " completed " in statuses[2]


def test_one_failure_among_several_runs_decides_the_verdict():
    clock = FakeClock()
    emitted: list[str] = []

    def fetch():
        return [
            _run(1, status="completed", conclusion="success"),
            _run(2, name="release", status="completed", conclusion="failure"),
        ]

    assert _watch(fetch, clock, emitted) == watch.EXIT_CONCLUDED_FAILURE
    assert any("did not succeed (failure)" in line for line in emitted)


def test_a_commit_that_runs_nothing_is_reported_at_the_appearance_deadline():
    clock = FakeClock()
    emitted: list[str] = []

    code = _watch(
        lambda: [], clock, emitted, appearance_timeout_seconds=90,
    )

    assert code == watch.EXIT_NO_RUN_FOUND
    assert any(line.startswith("CI run not found:") for line in emitted)
    assert any("has not appeared yet" in line for line in emitted)


def test_a_run_still_going_at_the_deadline_is_reported_as_such():
    clock = FakeClock()
    emitted: list[str] = []

    code = _watch(
        lambda: [_run(1, status="in_progress")],
        clock,
        emitted,
        timeout_seconds=100,
    )

    assert code == watch.EXIT_STILL_RUNNING
    assert any(line.startswith("CI run timeout:") for line in emitted)


def test_a_transient_read_failure_is_reported_and_retried():
    """A blip must not end a watch the deadline is there to bound."""
    from yoke_core.domain.gh_rest_transport import RestTransportError

    clock = FakeClock()
    emitted: list[str] = []
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RestTransportError("connection reset")
        return [_run(1, status="completed", conclusion="success")]

    assert _watch(fetch, clock, emitted) == watch.EXIT_SUCCESS
    assert any(line.startswith("Error:") for line in emitted)
    assert calls["n"] == 2


def test_the_target_line_names_what_is_being_watched():
    clock = FakeClock()
    emitted: list[str] = []

    _watch(
        lambda: [_run(1, status="completed", conclusion="success")],
        clock,
        emitted,
    )

    assert emitted[0] == (
        f"CI run target: repo=owner/name sha={'a' * 40} ref=HEAD "
        "workflow=(any)"
    )
