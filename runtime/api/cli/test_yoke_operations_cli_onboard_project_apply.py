"""Applied project-onboarding command coverage."""

from __future__ import annotations

import json
from pathlib import Path

from runtime.api.cli.project_onboarding_test_helpers import ProjectOnboardApi, run_git
from yoke_cli import main as yoke_operations_cli


def test_onboard_yes_writes_machine_config_and_project_handoff(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    home = tmp_path / "home"
    config = home / "config.json"
    checkout = tmp_path / "local-checkout"
    checkout.mkdir()
    run_git(checkout, "init")
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    with ProjectOnboardApi(
        project={
            "id": 44,
            "slug": "local",
            "name": "Local",
            "github_repo": "owner/local",
            "default_branch": "main",
            "public_item_prefix": "LOC",
        },
    ) as api:
        rc = yoke_operations_cli.main(
            [
                "onboard",
                "actor-token",
                "--non-interactive",
                "--quick",
                "--config",
                str(config),
                "--env",
                "prod",
                "--api-url",
                api.url,
                "--skip-identity-check",
                "--project-mode",
                "local-checkout",
                "--checkout",
                str(checkout),
                "--project-slug",
                "local",
                "--project-name",
                "Local",
                "--github-repo",
                "owner/local",
                "--default-branch",
                "main",
                "--public-item-prefix",
                "LOC",
                "--github-adoption",
                "disabled",
                "--yes",
                "--json",
            ]
        )
    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["applied"] is True
    assert payload["message"] == "machine config and project handoff written"
    project_report = payload["project_onboarding"]
    assert project_report["applied"] is True
    assert project_report["project"]["id"] == 44
    assert project_report["handoff"]["run_id"] == "run-handoff"
    assert project_report["handoff"]["agent_command"].startswith(
        "/yoke onboard --run-id "
    )
    assert project_report["github_adoption"]["choice"] == "disabled"
    assert api.function_call("projects.get")["payload"] == {"project": "local"}
    assert api.function_calls("projects.create") == []
    checklist_call = api.function_call("onboard.checklist.run")
    assert checklist_call["payload"]["project_id"] == 44
    assert checklist_call["payload"]["checkout_path"] == str(checkout.resolve())
    written = json.loads(config.read_text(encoding="utf-8"))
    assert written["active_env"] == "prod"
    assert written["projects"] == [
        {"checkout": str(checkout.resolve()), "project_id": 44, "env": "prod"},
    ]
    assert (checkout / ".yoke/install-manifest.json").is_file()
    assert "actor-token" not in out
    assert "actor-token" not in config.read_text(encoding="utf-8")
