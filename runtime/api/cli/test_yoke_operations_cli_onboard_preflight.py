"""Consolidated Review pre-flight re-check for the onboarding wizard.

``preflight_problems`` re-runs the relevant checks on the collected result and
returns the ordered list of remaining problems (empty == clear to apply). The
filesystem checks run against real temp paths; the network probes are injected so
no test reaches GitHub.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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
    machine_github_token: str | None = None
    machine_github_api_url: str | None = None
    env_name: str = "prod"
    token: str | None = None
    token_file: str | None = None
    machine_github_choice: str | None = "skip"
    machine_github_token_file: str | None = None


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


def test_revoked_token_is_flagged(tmp_path: Path) -> None:
    result = _Result(
        project_mode=onboard_project.PROJECT_MODE_CREATE_REPO,
        project_checkout=str(tmp_path / "fresh"),
        machine_github_token="ghs_revoked",
    )
    probes = onboard_preflight.PreflightProbes(
        token_ok=lambda _api, _token: False,
    )
    problems = onboard_preflight.preflight_problems(result, probes=probes)
    assert any("no longer works" in p for p in problems)


def test_populated_repo_name_is_flagged(tmp_path: Path) -> None:
    seen: dict = {}

    def _repo_availability(api_url, token, owner, name) -> str:
        seen.update(api_url=api_url, token=token, owner=owner, name=name)
        return onboard_preflight.REPO_POPULATED_BLOCKING

    result = _Result(
        project_mode=onboard_project.PROJECT_MODE_CREATE_REPO,
        project_checkout=str(tmp_path / "fresh"),
        project_publish_to_github=True,
        project_publish_owner="octocat",
        project_publish_repo_name="widget",
        machine_github_token="ghs_ok",
    )
    probes = onboard_preflight.PreflightProbes(
        token_ok=lambda _api, _token: True,
        repo_availability=_repo_availability,
    )
    problems = onboard_preflight.preflight_problems(result, probes=probes)
    assert any("already exists and has content" in p for p in problems)
    # The probe authenticated with the connected token and the chosen owner/name.
    assert seen == {
        "api_url": "https://api.github.com", "token": "ghs_ok",
        "owner": "octocat", "name": "widget",
    }


def test_free_repo_name_is_clear(tmp_path: Path) -> None:
    result = _Result(
        project_mode=onboard_project.PROJECT_MODE_CREATE_REPO,
        project_checkout=str(tmp_path / "fresh"),
        project_publish_to_github=True,
        project_publish_owner="octocat",
        project_publish_repo_name="widget",
        machine_github_token="ghs_ok",
    )
    probes = onboard_preflight.PreflightProbes(
        token_ok=lambda _api, _token: True,
        repo_availability=(
            lambda _api, _token, _owner, _name: onboard_preflight.REPO_FREE
        ),
    )
    assert onboard_preflight.preflight_problems(result, probes=probes) == []


def test_empty_existing_repo_is_resumable(tmp_path: Path) -> None:
    result = _Result(
        project_mode=onboard_project.PROJECT_MODE_CREATE_REPO,
        project_checkout=str(tmp_path / "fresh"),
        project_publish_to_github=True,
        project_publish_owner="octocat",
        project_publish_repo_name="widget",
        machine_github_token="ghs_ok",
    )
    probes = onboard_preflight.PreflightProbes(
        token_ok=lambda _api, _token: True,
        repo_availability=lambda *_: onboard_preflight.REPO_EMPTY_RESUMABLE,
    )
    assert onboard_preflight.preflight_problems(result, probes=probes) == []


def test_empty_existing_repo_surfaces_reuse_note(tmp_path: Path) -> None:
    """An existing empty repo does not block, but Review announces the reuse."""
    result = _Result(
        project_mode=onboard_project.PROJECT_MODE_CREATE_REPO,
        project_checkout=str(tmp_path / "fresh"),
        project_publish_to_github=True,
        project_publish_owner="octocat",
        project_publish_repo_name="widget",
        machine_github_token="ghs_ok",
    )
    probes = onboard_preflight.PreflightProbes(
        token_ok=lambda _api, _token: True,
        repo_availability=lambda *_: onboard_preflight.REPO_EMPTY_RESUMABLE,
    )
    checks = onboard_preflight.preflight(result, probes=probes)
    assert checks.problems == []
    assert any(
        "octocat/widget" in n and "reuse" in n.lower() for n in checks.notes
    )


def test_ambiguous_repo_probe_blocks_apply(tmp_path: Path) -> None:
    result = _Result(
        project_mode=onboard_project.PROJECT_MODE_CREATE_REPO,
        project_checkout=str(tmp_path / "fresh"),
        project_publish_to_github=True,
        project_publish_owner="octocat",
        project_publish_repo_name="widget",
        machine_github_token="ghs_ok",
    )
    probes = onboard_preflight.PreflightProbes(
        token_ok=lambda _api, _token: True,
        repo_availability=lambda *_: onboard_preflight.REPO_AMBIGUOUS_BLOCKING,
    )
    problems = onboard_preflight.preflight_problems(result, probes=probes)
    assert any("Couldn't prove octocat/widget is available" in p for p in problems)


def test_default_repo_classifier_splits_empty_and_populated(monkeypatch) -> None:
    statuses: dict[str, int] = {
        "/repos/octocat/widget": 200,
        "/repos/octocat/widget/commits": 409,
        "/repos/octocat/full": 200,
        "/repos/octocat/full/commits": 200,
    }

    def fake_probe(_api, path, _token, *, method, body):
        assert method == "GET"
        assert body is None
        return statuses.get(path)

    monkeypatch.setattr(
        "yoke_cli.config.github_token_capability.probe_status", fake_probe
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


def test_all_problems_reported_together(tmp_path: Path) -> None:
    # A filled clone target AND a revoked token surface in one pass, not one at a
    # time — the whole point of the consolidated re-check.
    full = tmp_path / "full"
    full.mkdir()
    (full / "f.txt").write_text("x", encoding="utf-8")
    result = _Result(
        project_mode=onboard_project.PROJECT_MODE_CLONE_REMOTE,
        project_remote_url="https://github.com/acme/widgets.git",
        project_checkout=str(full),
        machine_github_token="ghs_revoked",
    )
    probes = onboard_preflight.PreflightProbes(token_ok=lambda _a, _t: False)
    problems = onboard_preflight.preflight_problems(result, probes=probes)
    assert any("already has files" in p for p in problems)
    assert any("no longer works" in p for p in problems)


def test_missing_git_is_flagged(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(project_git_prerequisite.shutil, "which", lambda _name: None)
    result = _Result(
        project_mode=onboard_project.PROJECT_MODE_CREATE_REPO,
        project_checkout=str(tmp_path / "fresh"),
    )
    problems = onboard_preflight.preflight_problems(result)
    assert any("git is required" in p for p in problems)
