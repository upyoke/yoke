from __future__ import annotations

import json
from pathlib import Path

from runtime.api.cli.project_clone_test_support import allow_local_clone
from runtime.api.cli.project_onboarding_test_helpers import (
    ProjectOnboardApi,
    run_git,
    seed_remote,
)
from yoke_cli.config import onboard as onboard_config
from yoke_cli.config import onboard_machine_github
from yoke_cli.config import onboard_project
from yoke_cli.config import writer as machine_writer


def test_onboard_yes_reuses_existing_machine_and_project_state(
    tmp_path: Path, monkeypatch,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    config = home / "config.json"
    secrets = home / "secrets"
    secrets.mkdir(parents=True)
    token = secrets / "prod.token"
    token.write_text("actor-token\n", encoding="utf-8")
    github_refresh = secrets / "github.user-refresh"
    github_refresh.write_text("refresh\n", encoding="utf-8")
    temp_root = home / "tmp"
    cache_dir = home / "cache"
    temp_root.mkdir()
    cache_dir.mkdir()
    checkout = tmp_path / "local-checkout"
    checkout.mkdir()
    run_git(checkout, "init")
    (checkout / ".yoke").mkdir()
    (checkout / ".yoke" / "install-manifest.json").write_text(
        json.dumps({"manifest_schema": 1, "project_id": 44}) + "\n",
        encoding="utf-8",
    )
    events: list[tuple[str, str, str]] = []

    def unexpected_write(*_args, **_kwargs):
        raise AssertionError("unexpected machine config rewrite")

    monkeypatch.setattr(machine_writer, "set_connection", unexpected_write)
    monkeypatch.setattr(machine_writer, "set_active_env", unexpected_write)
    monkeypatch.setattr(machine_writer, "set_runtime_paths", unexpected_write)
    monkeypatch.setattr(machine_writer, "set_github", unexpected_write)
    monkeypatch.setattr(machine_writer, "register_project", unexpected_write)

    def unexpected_github_apply(*_args, **_kwargs):
        raise AssertionError("unexpected machine GitHub apply")

    monkeypatch.setattr(onboard_machine_github, "apply", unexpected_github_apply)

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
        config.write_text(json.dumps({
            "schema_version": 1,
            "active_env": "prod",
            "connections": {
                "prod": {
                    "transport": "https",
                    "api_url": api.url,
                    "credential_source": {"kind": "token_file", "path": str(token)},
                },
            },
            "github": {
                "api_url": "https://api.github.com",
                "app_slug": "yoke",
                "client_id": "Iv1.example",
                "authorization": {
                    "kind": "github_app_user_authorization",
                    "refresh_credential_ref": str(github_refresh),
                    "github_user_id": 1001,
                    "login": "machine-user",
                    "status": "authorized",
                },
            },
            "temp_root": str(temp_root),
            "cache_dir": str(cache_dir),
            "projects": {str(checkout.resolve()): {"project_id": 44}},
        }, indent=2) + "\n", encoding="utf-8")
        before_config = json.loads(config.read_text(encoding="utf-8"))

        report = onboard_config.build_report(
            config_path=config,
            env_name="prod",
            api_url=api.url,
            token_file=token,
            token_source_kind="token_file",
            mode="quick",
            apply=True,
            check_identity=False,
            machine_github_choice=onboard_machine_github.CHOICE_CONNECT,
            machine_github_api_url="https://api.github.com",
            project_mode="local-checkout",
            project_checkout=checkout,
            project_slug="local",
            project_name="Local",
            project_github_repo="owner/local",
            project_default_branch="main",
            project_public_item_prefix="LOC",
            existing_project_id=44,
            project_github_adoption="backlog-only",
            progress=lambda action, target, status: events.append(
                (action, target, status)
            ),
        )

    project_events = [event for event in events if event[0].startswith("project-")]
    actions = [step["action"] for step in report["plan"]["steps"]]

    assert actions == [
        "project-refresh-scaffold",
        "project-write-board-art",
        "project-github-auth-choice",
    ]
    assert project_events == [
        ("project-refresh-scaffold", "", "running"),
        ("project-refresh-scaffold", "", "done"),
        ("project-github-auth-choice", "existing-project", "skipped"),
    ]
    assert report["plan"]["reuse"]["project_checkout"] is True
    assert report["plan"]["reuse"]["project_scaffold"] is True
    assert report["plan"]["machine_github_mutation"] is False
    assert report["machine_github"]["writes_machine_secret"] is False
    assert report["machine_github"]["requires_browser_flow"] is False
    assert report["machine_github"]["reused"] is True
    assert report["project_onboarding"]["install"]["operation"] == "refresh"
    assert json.loads(config.read_text(encoding="utf-8")) == before_config

    get_call = api.function_call("projects.get")
    assert get_call["payload"] == {"project": "44"}
    assert api.function_calls("projects.create") == []
    assert api.requests_for("GET", "/v1/projects/44/install-bundle")


def test_onboard_preview_detects_matching_clone_reuse(
    tmp_path: Path, monkeypatch,
) -> None:
    remote = seed_remote(tmp_path)
    allow_local_clone(monkeypatch)
    checkout = tmp_path / "clone"
    run_git(tmp_path, "clone", str(remote), str(checkout))

    report = onboard_config.build_report(
        config_path=tmp_path / "home" / "config.json",
        env_name="prod",
        api_url="https://api.test",
        token="token",
        token_source_kind="argument",
        mode="quick",
        apply=False,
        check_identity=False,
        project_mode=onboard_config.PROJECT_MODE_CLONE_REMOTE,
        project_remote_url=str(remote),
        project_checkout=checkout,
        project_slug="clone",
        project_name="Clone",
        project_github_repo="owner/clone",
        project_default_branch="trunk",
        project_default_branch_source=(
            onboard_project.DEFAULT_BRANCH_SOURCE_SOURCE_REPO
        ),
        project_public_item_prefix="CLN",
        project_github_adoption="backlog-only",
    )

    assert report["plan"]["reuse"]["project_clone_checkout"] is True
    rendered = onboard_config.render_human(report)
    assert f"Matching clone already exists at {checkout}; Apply will reuse it." in rendered
    assert "Using detected source default branch: trunk." in rendered
