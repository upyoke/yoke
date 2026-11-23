"""A resumed setup wizard reopens at Review with the run's saved answers."""

from __future__ import annotations

import argparse
from types import SimpleNamespace

from yoke_cli.config import onboard_apply_snapshot, onboard_project_prefixes
from yoke_cli.config import onboard_wizard_resume_seed as seed
from yoke_cli.config import setup_release_marker
from yoke_cli.config.onboard_apply_report import ApplyReportWriter
from yoke_cli.config.onboard_wizard import WizardResult
from yoke_cli.config.onboard_wizard_path import PathFlow


def _payload() -> dict:
    kwargs = {
        "env_name": "acme",
        "api_url": "https://yoke.example/api/orgs/acme",
        "project_mode": "create-repo",
        "project_checkout": "/work/qa",
        "project_slug": "qa",
        "project_name": "QA",
        "project_public_item_prefix": "QA5638",
        "machine_github_choice": "skip",
        "hosting_choice": "undecided",
        "hosting_provider_note": "",
        "board_art": {"word": "QA", "seed": "abc123"},
    }
    return {"run_id": "run-1", "input_snapshot": onboard_apply_snapshot.build(kwargs)}


def _parsed(payload: dict) -> argparse.Namespace:
    project = payload["input_snapshot"]["project"]
    return argparse.Namespace(
        resume_run_id="run-1",
        resume_payload=payload,
        env_name="acme",
        api_url="https://yoke.example/api/orgs/acme",
        project_mode=project["mode"],
        project_checkout=project["checkout"],
        project_slug=project["slug"],
        project_name=project["name"],
        project_public_item_prefix=project["public_item_prefix"],
        machine_github_choice="skip",
        github_adoption="disabled",
        project_default_branch_source="",
    )


def test_snapshot_keeps_the_wizard_only_answers():
    snapshot = _payload()["input_snapshot"]

    assert snapshot["hosting"] == {"choice": "undecided", "provider_note": ""}
    assert snapshot["board_art"] == {"word": "QA", "seed": "abc123"}


def test_resume_answers_restore_project_github_hosting_and_art():
    answers = seed.answers(_parsed(_payload()))

    result = answers["result"]
    assert answers["run_id"] == "run-1"
    assert result["project_mode"] == "create-repo"
    assert result["project_public_item_prefix"] == "QA5638"
    assert result["project_github_adoption"] == "disabled"
    assert result["machine_github_choice"] == "skip"
    assert result["hosting_choice"] == "undecided"
    assert result["board_art_word"] == "QA" and result["board_art_variants"]


def test_not_resuming_seeds_nothing():
    assert seed.answers(argparse.Namespace(resume_run_id=None)) is None


def test_seeded_wizard_opens_at_review_after_the_install_check():
    shell = SimpleNamespace(
        result=WizardResult(config_path="/c", env_name="", api_url=""),
        _resume_run_id=None,
        _resume_payload=None,
    )
    seed.apply(shell, seed.answers(_parsed(_payload())))

    assert shell._resume_seeded and shell._resume_run_id == "run-1"
    assert shell.result.project_slug == "qa"
    assert shell.result.project_public_item_prefix == "QA5638"

    calls = []

    class Flow(PathFlow):
        _history: list = []
        _run_facts = SimpleNamespace(get=lambda _k: None, record=lambda *_a: None)

        def _goto_finish(self):
            calls.append("review")

        def _goto_project_mode(self, **_kwargs):
            calls.append("project-mode")

        def _start_connect(self):
            calls.append("connect")

    flow = Flow()
    flow.result = shell.result
    flow._resume_seeded = True
    flow._project_mode_preset = True
    flow._finish_install({"changed_files": []}, "")

    assert calls == ["review"]


def test_own_prefix_from_the_first_pass_is_not_a_conflict():
    holders = onboard_project_prefixes.holders_from_response(
        {
            "success": True,
            "result": {
                "rows": [
                    {"id": 73, "slug": "qa", "public_item_prefix": "QA5638"},
                    {"id": 9, "slug": "other", "public_item_prefix": "OTH"},
                ]
            },
        }
    )

    kept = onboard_project_prefixes.without_project(holders, "qa")

    assert "QA5638" not in kept and "OTH" in kept
    assert onboard_project_prefixes.without_project(None, "qa") is None


def test_resume_keeps_the_first_pass_checkout_ownership(tmp_path):
    folder = tmp_path / "qa"
    kwargs = {"project_mode": "create-repo", "project_checkout": str(folder)}
    first = onboard_apply_snapshot.build(kwargs)
    assert first["checkout_provenance"]["created_by_run"] is True
    first["checkout_provenance"]["ownership"] = {"token": "marker"}
    folder.mkdir()

    resumed = onboard_apply_snapshot.build(kwargs, {"input_snapshot": first})
    moved = onboard_apply_snapshot.build(
        {**kwargs, "project_checkout": str(tmp_path / "other")},
        {"input_snapshot": first},
    )

    assert resumed["checkout_provenance"] == first["checkout_provenance"]
    assert "ownership" not in moved["checkout_provenance"]


def test_report_records_a_follow_from_the_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    monkeypatch.setenv(
        setup_release_marker.FOLLOWED_RELEASE_ENV,
        setup_release_marker.encode("0.2.0.202611211930", "0.2.0.202611212023"),
    )
    writer = ApplyReportWriter.start({"plan": {"steps": []}}, {"apply": True})

    assert writer.payload["cli_followed_release"] == {
        "from": "0.2.0.202611211930",
        "to": "0.2.0.202611212023",
    }
