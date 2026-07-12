"""Consolidated Review pre-flight re-check for the onboarding wizard.

``preflight_problems`` re-runs the relevant checks on the collected result and
returns the ordered list of remaining problems (empty == clear to apply). The
filesystem checks run against real temp paths; the network probes are injected so
no test reaches GitHub.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import subprocess

from yoke_cli.config import onboard_preflight
from yoke_cli.config import onboard_project
from yoke_cli.config import project_git_prerequisite


@dataclass
class _Result:
    """Minimal stand-in for WizardResult carrying just the pre-flight inputs."""

    project_mode: str = onboard_project.PROJECT_MODE_MACHINE_ONLY
    project_checkout: str | None = None
    project_remote_url: str | None = None
    project_github_repo: str | None = None
    project_publish_to_github: bool = False
    project_publish_owner: str | None = None
    project_publish_repo_name: str | None = None
    machine_github_api_url: str | None = None
    config_path: str = "/tmp/yoke-test-config.json"
    env_name: str = "prod"
    token: str | None = None
    token_file: str | None = None
    machine_github_choice: str | None = "skip"
    project_clone_outcome: str | None = None
    project_github_adoption: str | None = None


def test_machine_only_is_always_clear() -> None:
    assert onboard_preflight.preflight_problems(_Result()) == []


def test_different_existing_yoke_token_blocks_review(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    saved = tmp_path / "home" / "secrets" / "stage.token"
    saved.parent.mkdir(parents=True)
    saved.write_text("yoke_v1_existing\n", encoding="utf-8")
    incoming = tmp_path / "incoming.token"
    incoming.write_text("yoke_v1_new\n", encoding="utf-8")

    problems = onboard_preflight.preflight_problems(
        _Result(env_name="stage", token_file=str(incoming))
    )

    assert any("different Yoke API token for stage" in p for p in problems)
    assert "yoke_v1_existing" not in "\n".join(problems)
    assert "yoke_v1_new" not in "\n".join(problems)


def test_same_existing_yoke_token_is_clear(
    tmp_path: Path, monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    saved = tmp_path / "home" / "secrets" / "stage.token"
    saved.parent.mkdir(parents=True)
    saved.write_text("yoke_v1_same\n", encoding="utf-8")

    assert onboard_preflight.preflight_problems(
        _Result(env_name="stage", token="yoke_v1_same")
    ) == []


def test_create_clear_for_a_fresh_target(tmp_path: Path) -> None:
    result = _Result(
        project_mode=onboard_project.PROJECT_MODE_CREATE_REPO,
        project_checkout=str(tmp_path / "fresh"),
    )
    assert onboard_preflight.preflight_problems(result) == []


def test_clone_target_that_filled_up_is_flagged(tmp_path: Path) -> None:
    full = tmp_path / "full"
    full.mkdir()
    (full / "f.txt").write_text("x", encoding="utf-8")
    result = _Result(
        project_mode=onboard_project.PROJECT_MODE_CLONE_REMOTE,
        project_remote_url="https://github.com/acme/widgets.git",
        project_checkout=str(full),
    )
    problems = onboard_preflight.preflight_problems(result)
    assert any("already has files" in p for p in problems)


def test_exact_existing_clone_is_safe_to_resume(tmp_path: Path) -> None:
    checkout = tmp_path / "existing-clone"
    checkout.mkdir()
    subprocess.run(
        ["git", "init", "--initial-branch", "main"],
        cwd=checkout, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    subprocess.run(
        [
            "git", "remote", "add", "origin",
            "https://github.com/acme/widgets.git",
        ],
        cwd=checkout, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    (checkout / "README.md").write_text("partial clone", encoding="utf-8")
    result = _Result(
        project_mode=onboard_project.PROJECT_MODE_CLONE_REMOTE,
        project_remote_url="git@github.com:acme/widgets.git",
        project_checkout=str(checkout),
    )

    assert onboard_preflight.preflight_problems(result) == []


def test_create_target_existing_dir_is_not_flagged(tmp_path: Path) -> None:
    # An existing non-empty dir is fine for create-new (it adopts) — no problem.
    full = tmp_path / "existing"
    full.mkdir()
    (full / "f.txt").write_text("x", encoding="utf-8")
    result = _Result(
        project_mode=onboard_project.PROJECT_MODE_CREATE_REPO,
        project_checkout=str(full),
    )
    assert onboard_preflight.preflight_problems(result) == []


def test_review_defers_live_github_checks_without_refreshing(
    tmp_path: Path,
) -> None:
    calls: list[str] = []
    result = _Result(
        project_mode=onboard_project.PROJECT_MODE_CREATE_REPO,
        project_checkout=str(tmp_path / "fresh"),
        project_publish_to_github=True,
        project_publish_owner="octocat",
        project_publish_repo_name="widget",
    )
    probes = onboard_preflight.PreflightProbes(
        token_ok=lambda *_: calls.append("token") or False,
        repo_availability=lambda *_: calls.append("repo") or (
            onboard_preflight.REPO_POPULATED_BLOCKING
        ),
    )
    checks = onboard_preflight.preflight(result, probes=probes)
    assert checks.problems == []
    assert checks.notes == ["Live GitHub access will be checked during Apply."]
    assert calls == []


def test_default_repo_classifier_splits_empty_and_populated(monkeypatch) -> None:
    statuses: dict[str, int] = {
        "/repos/octocat/widget": 200,
        "/repos/octocat/widget/commits": 409,
        "/repos/octocat/full": 200,
        "/repos/octocat/full/commits": 200,
    }

    def fake_request(_api, path, _token):
        from yoke_cli.config.github_publish_transport import GitHubPublishError

        status = statuses.get(path)
        if status == 200:
            return {}
        raise GitHubPublishError("probe", status=status)

    monkeypatch.setattr(
        "yoke_cli.config.github_publish_transport.request_json", fake_request
    )
    probes = onboard_preflight.default_probes()
    assert probes.repo_availability is not None
    assert probes.repo_availability(
        "https://api.github.com", "ghs_ok", "octocat", "widget"
    ) == onboard_preflight.REPO_EMPTY_RESUMABLE
    assert probes.repo_availability(
        "https://api.github.com", "ghs_ok", "octocat", "full"
    ) == onboard_preflight.REPO_POPULATED_BLOCKING
    assert probes.repo_availability(
        "https://api.github.com", "ghs_ok", "octocat", "missing"
    ) == onboard_preflight.REPO_AMBIGUOUS_BLOCKING


def test_folder_problem_still_blocks_without_live_github_check(
    tmp_path: Path,
) -> None:
    full = tmp_path / "full"
    full.mkdir()
    (full / "f.txt").write_text("x", encoding="utf-8")
    result = _Result(
        project_mode=onboard_project.PROJECT_MODE_CLONE_REMOTE,
        project_remote_url="https://github.com/acme/widgets.git",
        project_checkout=str(full),
    )
    problems = onboard_preflight.preflight_problems(result)
    assert any("already has files" in p for p in problems)


def test_missing_git_is_flagged(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(project_git_prerequisite.shutil, "which", lambda _name: None)
    result = _Result(
        project_mode=onboard_project.PROJECT_MODE_CREATE_REPO,
        project_checkout=str(tmp_path / "fresh"),
    )
    problems = onboard_preflight.preflight_problems(result)
    assert any("git is required" in p for p in problems)
