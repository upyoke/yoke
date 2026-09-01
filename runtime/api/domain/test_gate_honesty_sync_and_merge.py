"""Sync and merge paths name what did not happen instead of reporting green."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_core.domain import backlog_github_mirror_state as mirror
from yoke_core.domain import backlog_rendering
from yoke_core.domain import merge_queue_drift_gate
from yoke_core.domain import merge_queue_route_selection
from yoke_core.domain.capability_undeclare_remedy import undeclare_remedy
from yoke_core.domain.github_actions_workflow_inspection import (
    resolve_ci_workflow_binding,
)
from yoke_core.domain.merge_queue_batch_receipt import (
    BatchReceipt,
    record_batch_evidence,
)
from yoke_core.domain.merge_queue_live_drift import LiveDriftReport


class _Row(tuple):
    """A positional DB row, matching what the readers index into."""


class _FakeConn:
    def __init__(self, github_issue):
        self._github_issue = github_issue

    def execute(self, sql, params=()):
        return SimpleNamespace(fetchone=lambda: _Row((self._github_issue,)))


def _captured_absence_events(monkeypatch):
    """Capture the recorded absence rows without writing to a control plane."""
    seen: list[dict] = []
    monkeypatch.setattr(
        backlog_rendering,
        "_emit_event",
        lambda name, item_id, context: seen.append(dict(context, name=name)),
    )
    return seen


def test_create_without_an_issue_on_a_bound_project_reads_as_failure(
    monkeypatch, capsys
):
    seen = _captured_absence_events(monkeypatch)
    monkeypatch.setattr(
        backlog_rendering, "_resolve_project_github_repo", lambda conn, p: "org/repo"
    )
    recorded: list[tuple] = []
    monkeypatch.setattr(
        backlog_rendering,
        "_record_sync_failure",
        lambda item_id, operation, reason="unknown": recorded.append(
            (item_id, operation, reason)
        ),
    )
    state = mirror.record_mirror_state(
        _FakeConn(None),
        item_id=7,
        public_ref="YOK-7",
        project="yoke",
        attempt=mirror.MIRROR_ATTEMPT_FAILED,
    )
    assert state == mirror.MIRROR_STATE_FAILED
    assert recorded and recorded[0][1] == "create"
    assert seen[0]["mirror_state"] == mirror.MIRROR_STATE_FAILED
    assert "resync --fix" in capsys.readouterr().err


def test_create_without_a_bound_project_stamps_the_unmirrored_state(
    monkeypatch, capsys
):
    seen = _captured_absence_events(monkeypatch)
    monkeypatch.setattr(
        backlog_rendering, "_resolve_project_github_repo", lambda conn, p: ""
    )
    state = mirror.record_mirror_state(
        _FakeConn(None),
        item_id=7,
        public_ref="YOK-7",
        project="folder-only",
        attempt=mirror.MIRROR_ATTEMPT_SKIPPED,
    )
    assert state == mirror.MIRROR_STATE_UNMIRRORED
    assert seen[0]["github_app_bound"] is False
    assert "unmirrored" in capsys.readouterr().err


def test_a_mirrored_item_stamps_nothing_extra(monkeypatch):
    seen = _captured_absence_events(monkeypatch)
    state = mirror.record_mirror_state(
        _FakeConn("412"),
        item_id=7,
        public_ref="YOK-7",
        project="yoke",
        attempt=mirror.MIRROR_ATTEMPT_SYNCED,
    )
    assert state == mirror.MIRROR_STATE_MIRRORED
    assert seen == []


def test_a_skipped_drift_check_rides_the_batch_evidence():
    """Never fail-open silently: the batch says the comparison did not run."""
    skipped = LiveDriftReport(
        skip_reason="github_unreachable", skip_detail="GitHub 503"
    )
    assert merge_queue_drift_gate.drift_receipt(skipped) == {
        "status": "skipped",
        "skip_reason": "github_unreachable",
        "detail": "GitHub 503",
    }
    assert merge_queue_drift_gate.drift_receipt(LiveDriftReport()) == {
        "status": "compared"
    }

    recorded: dict = {}

    def dispatch(**kwargs):
        recorded.update(kwargs)
        return SimpleNamespace(success=True, error=None)

    error = record_batch_evidence(
        7,
        BatchReceipt(
            pr_num="9",
            head_sha="abc",
            drift_check=merge_queue_drift_gate.drift_receipt(skipped),
        ),
        dispatch=dispatch,
    )
    assert error is None
    assert '"drift_check"' in recorded["payload"]["raw_result"]
    assert "github_unreachable" in recorded["payload"]["raw_result"]


def test_a_declared_but_unreachable_ci_refusal_offers_undeclaring(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.github_actions_workflow_inspection"
        ".inspect_declared_workflow",
        lambda workflow_file, checkout: SimpleNamespace(
            reason_code="workflow_absent_from_repo",
            message="ci.yml is not in the repository",
        ),
    )
    try:
        resolve_ci_workflow_binding(
            "ci.yml", checkout=None, project="yoke", scope="full"
        )
    except ValueError as exc:
        message = str(exc)
    else:  # pragma: no cover - the refusal is the contract
        raise AssertionError("an unreachable declared workflow must refuse")
    assert "deliberately undeclare it" in message
    assert "--cap-type ci_workflow_file" in message
    assert "local runner" in message


def test_a_failed_merge_queue_probe_refusal_offers_undeclaring(monkeypatch):
    monkeypatch.setattr(
        merge_queue_route_selection,
        "project_declares_merge_queue",
        lambda project, dispatch=None: (False, "control plane unreachable"),
    )
    outcome = merge_queue_route_selection.route_standalone_landing(
        item_id=7,
        branch="YOK-7",
        target="main",
        repo_root="/repo",
        project="yoke",
    )
    assert outcome.ok is False
    assert "deliberately undeclare it" in outcome.error
    assert "--cap-type merge_queue" in outcome.error


def test_the_undeclare_remedy_is_written_once():
    remedy = undeclare_remedy("merge_queue", project="yoke", consequence="local")
    assert remedy.startswith("Either repair what the 'merge_queue' capability")
    assert "yoke projects capability-settings remove --project yoke" in remedy
    assert remedy.endswith("(local).")
