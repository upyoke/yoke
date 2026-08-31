"""The done ceremony refuses what it cannot prove and records what degraded."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_core.engines import done_transition_finalize as finalize
from yoke_core.engines import done_transition_github_sync as github_sync


class _Result:
    def __init__(self):
        self.steps: list[str] = []
        self.warnings: list[dict] = []

    def add_step(self, marker):
        self.steps.append(marker)


def test_a_degraded_finalization_lands_on_the_result(monkeypatch, capsys):
    monkeypatch.setattr(
        finalize,
        "call_dispatcher",
        lambda **kwargs: SimpleNamespace(
            success=False, error=SimpleNamespace(message="relay down"), result={}
        ),
    )
    result = _Result()
    note = finalize._finalize_done_local_side_effects(
        7, "internal", "Title", "yoke", "", result=result
    )
    assert "relay down" in note
    assert result.steps == ["6c-degraded"]
    assert result.warnings[0]["code"] == "done_finalization_degraded"
    assert "Degraded:" in capsys.readouterr().out


def test_a_clean_finalization_records_the_plain_step(monkeypatch):
    monkeypatch.setattr(
        finalize,
        "call_dispatcher",
        lambda **kwargs: SimpleNamespace(
            success=True, error=None, result={"deployed_to": "", "release_note": False}
        ),
    )
    result = _Result()
    assert (
        finalize._finalize_done_local_side_effects(
            7, "internal", "Title", "yoke", "", result=result
        )
        == ""
    )
    assert result.steps == ["6c"]
    assert result.warnings == []


def test_an_unreachable_github_closeout_is_recorded_on_the_sync(monkeypatch):
    """A skipped closeout is not a quieter failure than a degraded one."""
    monkeypatch.setattr(
        github_sync,
        "run_step_8",
        lambda item_id, old_status, stderr=None, public_ref=None: (
            github_sync.Step8Result(
                returncode=0, step_marker="8-skipped", message="module unreachable"
            )
        ),
    )
    recorded: list[tuple] = []
    monkeypatch.setattr(
        "yoke_core.domain.backlog_rendering._record_sync_failure",
        lambda item_id, operation, reason="unknown": recorded.append(
            (item_id, operation, reason)
        ),
    )
    result = _Result()
    outcome = github_sync.apply_step_8(7, "release", result, public_ref="YOK-7")
    assert outcome.is_incomplete is True
    assert result.steps == ["8-skipped"]
    assert result.warnings[0]["code"] == "github_sync_degraded"
    assert recorded and recorded[0][1] == "state"
