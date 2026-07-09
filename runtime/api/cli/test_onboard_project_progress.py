from __future__ import annotations

import json
from pathlib import Path

from runtime.api.cli.project_onboarding_test_helpers import (
    ProjectOnboardApi,
    run_git,
    seed_remote,
    write_https_config,
)
from yoke_cli import main as yoke_operations_cli
from yoke_cli.config import machine_config
from yoke_cli.config import onboard as onboard_config
from yoke_cli.config import writer as machine_writer


def test_project_apply_progress_events_follow_real_substeps(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    config = home / "config.json"
    checkout = tmp_path / "local-checkout"
    checkout.mkdir()
    run_git(checkout, "init")
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    events: list[tuple[str, str, str]] = []

    with ProjectOnboardApi(project=_project_row()) as api:
        onboard_config.build_report(
            config_path=config,
            env_name="prod",
            api_url=api.url,
            token="actor-token",
            mode="quick",
            apply=True,
            check_identity=False,
            project_mode="local-checkout",
            project_checkout=checkout,
            project_slug="local",
            project_name="Local",
            project_github_repo="owner/local",
            project_default_branch="main",
            project_public_item_prefix="LOC",
            project_github_adoption="backlog-only",
            progress=lambda action, target, status: events.append(
                (action, target, status)
            ),
        )

    project_events = [
        event for event in events if event[0].startswith("project-")
    ]
    assert project_events == [
        ("project-source-choice", "local-checkout", "done"),
        ("project-onboard-local-checkout", str(checkout), "running"),
        ("project-onboard-local-checkout", str(checkout), "done"),
        ("project-install-scaffold", "", "running"),
        ("project-checkout-register", str(checkout), "running"),
        ("project-checkout-register", str(checkout), "done"),
        ("project-install-scaffold", "", "done"),
        ("project-github-auth-choice", "backlog-only", "skipped"),
    ]


def test_apply_report_records_project_substep_statuses(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    home = tmp_path / "home"
    config = home / "config.json"
    checkout = tmp_path / "local-checkout"
    checkout.mkdir()
    run_git(checkout, "init")
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))

    with ProjectOnboardApi(project=_project_row()) as api:
        rc = yoke_operations_cli.main([
            "onboard",
            "actor-token",
            "--non-interactive",
            "--quick",
            "--config", str(config),
            "--env", "prod",
            "--api-url", api.url,
            "--skip-identity-check",
            "--project-mode", "local-checkout",
            "--checkout", str(checkout),
            "--project-slug", "local",
            "--project-name", "Local",
            "--github-repo", "owner/local",
            "--default-branch", "main",
            "--public-item-prefix", "LOC",
            "--github-adoption", "backlog-only",
            "--yes",
            "--json",
        ])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    report_path = Path(payload["apply_report"]["path"])
    report = json.loads(report_path.read_text(encoding="utf-8"))
    statuses = {
        step["action"]: step
        for step in report["steps"]
        if step["action"].startswith("project-")
    }
    assert statuses["project-source-choice"]["status"] == "done"
    assert statuses["project-onboard-local-checkout"]["status"] == "done"
    assert statuses["project-checkout-register"]["status"] == "done"
    assert statuses["project-install-scaffold"]["status"] == "done"
    assert statuses["project-github-auth-choice"]["status"] == "skipped"
    assert statuses["project-onboard-local-checkout"]["started_at"]
    assert statuses["project-checkout-register"]["started_at"]
    assert statuses["project-install-scaffold"]["started_at"]


def test_project_apply_progress_updates_stale_checkout_mapping(tmp_path: Path) -> None:
    checkout = tmp_path / "local-checkout"
    checkout.mkdir()
    run_git(checkout, "init")
    events: list[tuple[str, str, str]] = []

    with ProjectOnboardApi(project=_project_row()) as api:
        config = write_https_config(tmp_path, "actor-token", api.url)
        machine_writer.register_project(checkout, 12, path=config)
        onboard_config.build_report(
            config_path=config,
            env_name="prod",
            api_url=api.url,
            token="actor-token",
            mode="quick",
            apply=True,
            check_identity=False,
            project_mode="local-checkout",
            project_checkout=checkout,
            project_slug="local",
            project_name="Local",
            project_github_repo="owner/local",
            project_default_branch="main",
            project_public_item_prefix="LOC",
            project_github_adoption="skip",
            progress=lambda action, target, status: events.append(
                (action, target, status)
            ),
        )

    assert machine_config.project_id(checkout, config) == 44
    assert (
        "project-checkout-register", str(checkout), "running",
    ) in events
    assert (
        "project-checkout-register", str(checkout), "done",
    ) in events


def test_clone_resume_progress_marks_checkout_step_skipped(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    config = home / "config.json"
    remote = seed_remote(tmp_path)
    checkout = tmp_path / "clone"
    run_git(tmp_path, "clone", str(remote), str(checkout))
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    events: list[tuple[str, str, str]] = []

    with ProjectOnboardApi(project=_project_row(slug="clone")) as api:
        onboard_config.build_report(
            config_path=config,
            env_name="prod",
            api_url=api.url,
            token="actor-token",
            mode="quick",
            apply=True,
            check_identity=False,
            project_mode="clone-remote",
            project_remote_url=str(remote),
            project_checkout=checkout,
            project_slug="clone",
            project_name="Clone",
            project_github_repo="owner/clone",
            project_default_branch="trunk",
            project_public_item_prefix="CLN",
            project_github_adoption="skip",
            progress=lambda action, target, status: events.append(
                (action, target, status)
            ),
        )

    assert (
        "project-clone-remote", str(checkout), "skipped",
    ) in events
    assert (
        "project-install-scaffold", "", "running",
    ) in events


def _project_row(*, slug: str = "local") -> dict:
    return {
        "id": 44,
        "slug": slug,
        "name": slug.title(),
        "github_repo": f"owner/{slug}",
        "default_branch": "main",
        "public_item_prefix": "LOC",
    }
