"""Actual Fork destinations survive durable reports and later Apply failures."""

import json

import pytest

from yoke_cli.config import onboard_apply_report, onboard_publication_receipts as receipts
from yoke_cli.config import project_onboard, project_onboard_clone
from yoke_cli.config.project_clone_support import ClonePlan

SOURCE = "https://github.com/source/widgets.git"


@pytest.mark.parametrize("later_failure", [False, True])
def test_actual_fork_destination_is_saved_before_later_work(tmp_path, monkeypatch, later_failure):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    root = tmp_path / "checkout"
    root.mkdir()
    plan = ClonePlan(outcome="fork", fallback_token="fixture-only", fork_allowed=True)
    kwargs = {
        "project_checkout": str(root), "project_remote_url": SOURCE,
        "project_github_repo": "source/widgets", "project_clone": plan,
    }
    writer = onboard_apply_report.ApplyReportWriter.start({}, kwargs)
    assert writer.payload["target_github_repo"] == ""
    monkeypatch.setattr(project_onboard_clone, "prepare_clone_plan", lambda plan, *a, **k: plan)
    monkeypatch.setattr(project_onboard, "_resumable_clone", lambda *a, **k: True)
    monkeypatch.setattr(
        project_onboard, "_apply_clone_outcome",
        lambda *a, **k: project_onboard_clone.CloneApplyResult(
            github_repo="owner/widgets", branch="main",
        ),
    )

    def layer(*a, **k):
        persisted = json.loads(writer.path.read_text())
        assert persisted["target_github_repo"] == "owner/widgets"
        if later_failure:
            raise RuntimeError("later layer failure")

    monkeypatch.setattr(project_onboard.project_onboard_installed_layer, "apply_decision", layer)
    monkeypatch.setattr(project_onboard.progress_steps, "record_mutated_repository", lambda *a, **k: None)
    monkeypatch.setattr(project_onboard, "dispatch", lambda *a, **k: {})
    monkeypatch.setattr(project_onboard.project_onboard_apply, "finish_after_dispatch", lambda **k: {})
    monkeypatch.setattr(project_onboard, "_finish_github_binding", lambda *a: None)
    with receipts.recording(writer):
        try:
            project_onboard.import_project(
                remote_url=SOURCE, checkout=root, slug="copy", name="Copy", org=None,
                github_repo="source/widgets", default_branch="main", public_item_prefix="COPY",
                github_adoption_choice="disabled", config_path=None, apply=True, clone=plan,
            )
        except RuntimeError as error:
            assert later_failure
            assert str(error) == "later layer failure"
            writer.fail(error)
        else:
            assert not later_failure
            writer.finish()
    persisted = json.loads(writer.path.read_text())
    assert persisted["target_github_repo"] == "owner/widgets"
    assert persisted["source_repo"] == SOURCE
    assert persisted["input_snapshot"]["project"]["remote_url"] == SOURCE
    resumed = onboard_apply_report.ApplyReportWriter.start(
        {}, {**kwargs, "resume_payload": persisted, "resume_run_id": persisted["run_id"]},
    )
    assert resumed.payload["target_github_repo"] == "owner/widgets"


def test_foreign_checkout_does_not_replace_active_report_destination(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    root = tmp_path / "checkout"
    root.mkdir()
    writer = onboard_apply_report.ApplyReportWriter.start({}, {"project_checkout": str(root)})
    with receipts.recording(writer):
        receipts.record_destination(tmp_path / "other", "foreign/repo")
    assert json.loads(writer.path.read_text())["target_github_repo"] == ""
