"""Setup Apply records the publication it actually achieved on its own step."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_cli.commands.adapters import onboard_apply
from yoke_cli.config import onboard_publication
from yoke_cli.project_install import publication_outcome

PUBLICATION_TARGET = "Commit Yoke setup and push to origin main"


def _preview(*, with_publication: bool = True) -> dict:
    steps = [{"action": "project-install-scaffold", "target": ""}]
    if with_publication:
        steps.append(
            {"action": onboard_publication.PLAN_ACTION, "target": PUBLICATION_TARGET}
        )
    return {"config_path": "/tmp/home/config.json", "plan": {"project": None, "steps": steps}}


def _apply(
    monkeypatch: pytest.MonkeyPatch,
    publication: dict | None,
    *,
    with_publication: bool = True,
) -> dict:
    seen: list[tuple[str, str]] = []

    def fake_build_report(**kwargs):
        progress = kwargs.get("progress")
        if progress is None:
            return _preview(with_publication=with_publication)
        progress("project-install-scaffold", "", "running")
        progress("project-install-scaffold", "", "done")
        if publication is not None:
            progress(onboard_publication.PLAN_ACTION, "", "running")
            status = onboard_publication.step_status(publication)
            progress(onboard_publication.PLAN_ACTION, "", status)
            seen.append((onboard_publication.PLAN_ACTION, status))
        install = {"publication": publication} if publication is not None else {}
        return {"project_onboarding": {"install": install}}

    monkeypatch.setattr(onboard_apply.onboard_config, "build_report", fake_build_report)
    report = onboard_apply.apply_with_durable_report(
        {"apply": True, "path_repair": {}, "config_path": "/tmp/home/config.json"},
        install_health=False,
    )
    return json.loads(Path(report["apply_report"]["path"]).read_text(encoding="utf-8"))


def _publication_step(payload: dict) -> dict:
    return next(
        step for step in payload["steps"]
        if step["action"] == onboard_publication.PLAN_ACTION
    )


@pytest.fixture(autouse=True)
def _machine_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))


def test_published_setup_reports_done_with_its_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published = {
        "status": publication_outcome.PUBLISHED,
        "remote": "origin",
        "branch": "main",
        "commit": "a" * 40,
    }

    payload = _apply(monkeypatch, published)

    step = _publication_step(payload)
    assert step["status"] == "done"
    assert step["detail"]["commit"] == "a" * 40
    assert payload["final_status"] == "done"


def test_pending_publication_is_incomplete_never_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pending = {
        "status": publication_outcome.PENDING,
        "remote": "origin",
        "branch": "main",
        "commit": "b" * 40,
        "detail": "the remote refused the push",
        "recovery": "recipe: `git push origin main`",
    }

    payload = _apply(monkeypatch, pending)

    step = _publication_step(payload)
    assert step["status"] == "incomplete"
    assert step["error"] == "recipe: `git push origin main`"
    assert payload["final_status"] == onboard_publication.FINAL_STATUS_PENDING
    assert payload["failed_step"] is None


def test_skipped_publication_reports_its_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skipped = {
        "status": publication_outcome.SKIPPED,
        "reason": publication_outcome.LOCAL_ONLY_REASON,
    }

    payload = _apply(monkeypatch, skipped)

    step = _publication_step(payload)
    assert step["status"] == "skipped"
    assert step["detail"]["reason"] == publication_outcome.LOCAL_ONLY_REASON
    assert payload["final_status"] == onboard_publication.FINAL_STATUS_SKIPPED


def test_planned_publication_with_no_outcome_is_not_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _apply(monkeypatch, None)

    assert _publication_step(payload)["status"] == "skipped"
    assert payload["final_status"] == onboard_publication.FINAL_STATUS_SKIPPED


def test_run_without_a_publication_step_finishes_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _apply(monkeypatch, None, with_publication=False)

    assert payload["final_status"] == "done"
