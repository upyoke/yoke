"""Review-screen wording + list rendering for the "Develop Yoke itself" flow.

Covers the plain-language labels the onboard review shows (the core DB records
the PROJECT, not the checkout path; the source-dev github-auth line names the
clone's origin remote), and that the REVIEW plan derives the same github-auth
target as the apply path. The apply/engine seam lives in
``test_onboard_source_dev_apply.py``.
"""

from __future__ import annotations

from pathlib import Path

from yoke_cli.config import onboard_plan_labels
from yoke_cli.config import onboard_project
from yoke_cli.config import onboard_report
from yoke_cli.config import yoke_dev_detect
from yoke_cli.config import yoke_token_verify


def test_source_dev_source_choice_names_project_not_checkout() -> None:
    # F6: the core DB records the PROJECT, not this checkout's path (the path is
    # registered in config.json by the separate project-checkout-register step).
    line = onboard_plan_labels.friendly_line(
        "project-source-choice", "source-dev-admin", "Yoke",
    )
    assert line == "Register the Yoke project in the Yoke core database"
    assert "checkout" not in line


def test_source_dev_github_auth_target_and_label() -> None:
    # F7: source-dev gets Yoke's origin remote from the clone.
    assert onboard_project._github_auth_target(
        {}, mode=onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN,
    ) == "source-dev"
    assert onboard_project._github_auth_target({}) == "backlog-only"
    remote_line = onboard_plan_labels.friendly_line(
        "project-github-auth-choice", "source-dev",
    )
    assert "origin" in remote_line and "clone" in remote_line


def test_build_plan_source_dev_github_auth_step_is_source_dev(
    tmp_path: Path
) -> None:
    # F7 regression: the REVIEW plan (build_plan) — not only the apply path —
    # must render the source-dev github-auth target. The inline ternary used to
    # drop it to "skip"; build_plan now shares onboard_project._github_auth_target.
    plan = onboard_report.build_plan(
        tmp_path / "config.json",
        "stage",
        "https://api.stage.upyoke.com",
        {"kind": "token_file", "path": "/tmp/stage.token"},
        {"kind": "token_file", "path": "/tmp/stage.token"},
        "quick",
        project_mode=onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN,
        project_inputs={"checkout": str(tmp_path / "yoke"), "slug": "yoke"},
        machine_github={"choice": "connect"},
    )
    auth = [s for s in plan["steps"] if s["action"] == "project-github-auth-choice"]
    assert auth and auth[0]["target"] == "source-dev"


def test_source_dev_next_steps_open_new_shell(tmp_path: Path) -> None:
    steps = onboard_report.next_steps(
        tmp_path / "config.json", onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN,
    )
    assert any("new terminal" in step.lower() for step in steps)
    # The editable install now happens during apply, not as a manual next step.
    assert not any("--editable-install" in step for step in steps)


def test_reuse_summary_uses_distinct_already_labels() -> None:
    # The "already set up" review block must NOT repeat the write-plan group
    # labels, or the review renders "On this machine (~/.yoke)" twice (conflicting).
    from yoke_cli.config import onboard_wizard_plan_review as review

    plan_labels = {label for label, _c, _k in review._PLAN_GROUPS}
    reuse_labels = {label for label, _c, _k in review._REUSE_GROUPS}
    assert plan_labels.isdisjoint(reuse_labels)
    assert all(label.startswith("Already") for label in reuse_labels)


def test_bounded_entries_uses_and_n_more() -> None:
    # F4: the Yoke orgs/projects list (a separate screen from the GitHub lists).
    assert yoke_token_verify._bounded_entries(["a", "b"]) == "a, b"
    assert yoke_token_verify._bounded_entries(list("abcdefg")) == (
        "a, b, c, d, and 3 more"
    )


def test_source_dev_checkout_default_dir_leads_with_code_yoke() -> None:
    # F5: the default checkout folder matches ~/code/<project> like other modes.
    assert yoke_dev_detect._COMMON_CHECKOUT_DIRS[0] == "~/code/yoke"


def test_source_dev_checkout_preflight_refuses_non_yoke_folder(
    tmp_path: Path,
) -> None:
    conflict = tmp_path / "not-yoke"
    conflict.mkdir()
    (conflict / "README.md").write_text("not yoke\n", encoding="utf-8")

    error = yoke_dev_detect.preflight_dev_checkout(str(conflict))

    assert error is not None
    assert "already has files" in error
    assert "not a Yoke source checkout" in error


def test_project_report_clones_yoke_repo_for_source_dev(
    tmp_path: Path, monkeypatch
) -> None:
    # F1: source-dev onboarding passes Yoke's own repo as the clone target + the
    # short-lived GitHub App user access, so a fresh folder is cloned (not git-init'd empty).
    captured: dict = {}
    monkeypatch.setattr(
        onboard_project.project_onboard, "onboard_existing",
        lambda **kw: captured.update(kw) or {"ok": True},
    )
    monkeypatch.setattr(
        onboard_project, "_github_user_access_token", lambda cfg: "gh-tok",
    )

    onboard_project._project_report(
        config_path=tmp_path / "config.json",
        apply=True,
        inputs={
            "mode": "source-dev-admin",
            "checkout": str(tmp_path / "yoke"),
            "slug": "yoke",
            "name": "Yoke",
            "default_branch": "main",
            "public_item_prefix": "YOK",
        },
        reuse=None,
        progress=None,
    )

    assert "yoke" in (captured["clone_remote_url"] or "")
    assert captured["clone_token"] == "gh-tok"
