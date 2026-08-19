"""Bounded observation of checks on a pushed standalone merge commit."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_contracts.machine_config.settings_keys import (
    is_recognized,
    machine_setting_default,
)
from yoke_core.domain import standalone_item_merge_post_push as post_push
from yoke_core.domain.project_github_auth_models import (
    GITHUB_AUTHORITY_INSTALLATION,
)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _run(
    monkeypatch,
    readings,
    *,
    discovery: int = 90,
    conclusion: int = 900,
):
    clock = Clock()
    seen: list[float] = []
    pending = list(readings)

    def read(_project, _sha, _authority):
        seen.append(clock.now)
        return pending.pop(0) if len(pending) > 1 else pending[0]

    def setting(key):
        return discovery if key == post_push.DISCOVERY_TIMEOUT_KEY else conclusion

    monkeypatch.setattr(post_push, "_setting_seconds", setting)
    verdict = post_push.await_post_push_checks(
        "yoke", "merge-sha", GITHUB_AUTHORITY_INSTALLATION, read=read,
        sleep=clock.sleep, monotonic=clock.monotonic,
    )
    return verdict, clock, seen


def _check(status: str, conclusion: str = "", *, name: str = "ci"):
    return post_push.CheckRun(
        name=name,
        status=status,
        conclusion=conclusion,
        url=f"https://runs/{name}",
    )


def test_a_failing_run_is_terminal_and_names_its_url(monkeypatch) -> None:
    verdict, clock, seen = _run(
        monkeypatch,
        [((_check("completed", "failure", name="contract"),), "")],
    )

    assert verdict.kind == "failed"
    assert not verdict.ok
    assert verdict.runs[0].url == "https://runs/contract"
    assert clock.sleeps == []
    assert seen == [0.0]


def test_no_runs_inside_the_discovery_window_is_ci_less(monkeypatch) -> None:
    verdict, clock, seen = _run(monkeypatch, [((), "")])

    assert verdict.kind == "no_checks"
    assert verdict.ok
    assert seen == [0.0, 60.0]
    assert clock.sleeps == [60.0, 30.0]


def test_pending_runs_are_polled_until_every_conclusion_is_green(monkeypatch) -> None:
    verdict, clock, seen = _run(
        monkeypatch,
        [
            ((_check("in_progress"),), ""),
            ((_check("completed", "success"),), ""),
        ],
    )

    assert verdict.kind == "passed"
    assert verdict.ok
    assert verdict.evidence[0]["conclusion"] == "success"
    assert seen == [0.0, 60.0]
    assert clock.sleeps == [60.0]


def test_pending_timeout_never_reads_faster_than_the_shared_floor(
    monkeypatch,
) -> None:
    verdict, clock, seen = _run(
        monkeypatch,
        [((_check("in_progress"),), "")],
        conclusion=150,
    )

    assert verdict.kind == "timed_out"
    assert not verdict.ok
    assert seen == [0.0, 60.0, 120.0]
    assert all(later - earlier >= 60 for earlier, later in zip(seen, seen[1:]))
    assert clock.sleeps == [60.0, 60.0, 30.0]


def test_post_push_timeouts_are_recognized_machine_settings() -> None:
    assert is_recognized(post_push.DISCOVERY_TIMEOUT_KEY)
    assert is_recognized(post_push.CONCLUSION_TIMEOUT_KEY)
    assert machine_setting_default(post_push.DISCOVERY_TIMEOUT_KEY) == "90"
    assert machine_setting_default(post_push.CONCLUSION_TIMEOUT_KEY) == "900"


def test_check_run_reader_keeps_conclusions_and_urls(monkeypatch) -> None:
    monkeypatch.setattr(
        post_push,
        "resolve_auth",
        lambda *_a, **_k: SimpleNamespace(repo="upyoke/yoke", token="token"),
    )
    monkeypatch.setattr(
        post_push,
        "request_with_retry",
        lambda request, **_k: SimpleNamespace(body={"check_runs": [{
            "name": "suite",
            "status": "completed",
            "conclusion": "success",
            "html_url": "https://runs/suite",
        }]}),
    )

    runs, error = post_push.read_check_runs(
        "yoke", "abc123", GITHUB_AUTHORITY_INSTALLATION,
    )

    assert error == ""
    assert runs == (
        post_push.CheckRun(
            name="suite", status="completed", conclusion="success",
            url="https://runs/suite",
        ),
    )
