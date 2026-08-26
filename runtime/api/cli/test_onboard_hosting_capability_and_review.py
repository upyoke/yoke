"""Hosting bootstrap link, plan rows, and the review screen's honesty deltas.

Pure-function coverage that needs no Textual app: the one-click link a build
offers, the write-plan row and label the hosting answer produces, and the
review copy that has to stay truthful once secrets are on disk before Apply.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_cli.config import aws_admin_capability as hosting
from yoke_contracts import hosting_posture
from yoke_cli.config import onboard_plan_labels
from yoke_cli.config import onboard_project
from yoke_cli.config import onboard_project_modes
from yoke_cli.config import onboard_report
from yoke_cli.config import onboard_reuse_feedback
from yoke_cli.config import onboard_reuse_state
from yoke_cli.config import onboard_wizard_review_steps as review_steps

_VERSION = "1.4.2"
_BASE = "https://api.upyoke.com"


# --------------------------------------------------------------------------- #
# The one-click link
# --------------------------------------------------------------------------- #


def test_link_pins_the_running_builds_template() -> None:
    """The launched template is the one published with this exact build."""
    url = hosting.quick_create_url(
        region="eu-west-1",
        version=_VERSION,
        base_url=_BASE,
    )

    assert url is not None
    assert f"{_BASE}/dist/releases/{_VERSION}/yoke-aws-admin.yaml" in url
    assert "region=eu-west-1" in url
    assert f"stackName={hosting.BOOTSTRAP_STACK_NAME}" in url


def test_link_is_absent_for_a_build_with_no_published_version() -> None:
    """A source checkout publishes no template, so it offers no link."""
    assert hosting.quick_create_url(version="", base_url=_BASE) is None
    assert hosting.template_url(version="", base_url=_BASE) is None


def test_link_honors_the_distribution_host_override(monkeypatch) -> None:
    monkeypatch.setenv("YOKE_INSTALL_BASE_URL", "https://api.stage.upyoke.com/")
    url = hosting.quick_create_url(region="us-east-1", version=_VERSION)

    assert url is not None
    assert "https://api.stage.upyoke.com/dist/releases/" in url


def test_region_follows_the_ambient_aws_region(monkeypatch) -> None:
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    monkeypatch.setenv("AWS_REGION", "ap-southeast-2")
    assert hosting.default_region() == "ap-southeast-2"

    monkeypatch.delenv("AWS_REGION", raising=False)
    assert hosting.default_region() == hosting.DEFAULT_REGION


# --------------------------------------------------------------------------- #
# Machine-local custody
# --------------------------------------------------------------------------- #


def test_credential_presence_needs_both_halves(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / ".yoke"))
    directory = hosting.credential_dir("acme-app")
    directory.mkdir(parents=True)

    assert hosting.credential_saved("acme-app") is False
    (directory / hosting.ACCESS_KEY_ID_KEY).write_text("AKIA\n", encoding="utf-8")
    assert hosting.credential_saved("acme-app") is False
    (directory / hosting.SECRET_ACCESS_KEY_KEY).write_text("s\n", encoding="utf-8")
    assert hosting.credential_saved("acme-app") is True
    # A different project's credential is not this project's.
    assert hosting.credential_saved("other-app") is False


def test_credential_directory_reads_the_same_on_every_machine(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Custody copy names the path on screen, so it must not leak a home dir."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / ".yoke"))

    assert hosting.credential_dir_display("acme-app") == (
        "~/.yoke/secrets/capability-secrets/acme-app/aws-admin/"
    )
    assert hosting.credential_dir_display("") == ""


# --------------------------------------------------------------------------- #
# The write plan
# --------------------------------------------------------------------------- #


def _plan(*, project_mode: str, hosting_choice: str, reuse: dict) -> dict:
    return onboard_report.build_plan(
        Path("/home/.yoke/config.json"),
        "prod",
        "https://api.test",
        {"kind": "token_file", "path": "/home/.yoke/secrets/prod.token"},
        {"kind": "token_file", "path": "/home/.yoke/secrets/prod.token"},
        "quick",
        project_mode=project_mode,
        project_inputs={
            "mode": project_mode,
            "checkout": "/home/code/acme-app",
            "slug": "acme-app",
            "name": "Acme App",
            "github_adoption": "disabled",
        },
        machine_github={"choice": "skip"},
        hosting_choice=hosting_choice,
        reuse=reuse,
    )


def test_plan_names_a_skipped_hosting_answer() -> None:
    plan = _plan(
        project_mode=onboard_project.PROJECT_MODE_LOCAL_CHECKOUT,
        hosting_choice=hosting_posture.POSTURE_UNDECIDED,
        reuse={},
    )
    row = next(
        step
        for step in plan["steps"]
        if step["action"] == hosting_posture.HOSTING_POSTURE_ACTION
    )

    assert row["target"] == hosting_posture.POSTURE_UNDECIDED
    assert onboard_plan_labels.friendly_line(row["action"], row["target"]) == (
        "Skip connecting a hosting provider for now"
    )


def test_a_saved_credential_moves_out_of_the_write_plan() -> None:
    """Already on disk means the reuse block names it, not the Apply plan."""
    plan = _plan(
        project_mode=onboard_project.PROJECT_MODE_LOCAL_CHECKOUT,
        hosting_choice=hosting_posture.POSTURE_YOKE_MANAGED_AWS,
        reuse={"aws_admin": True},
    )

    assert all(
        step["action"] != hosting_posture.HOSTING_POSTURE_ACTION for step in plan["steps"]
    )
    assert onboard_reuse_feedback.grouped_lines_for_plan(plan)["machine"] == [
        "The aws-admin hosting credential (2 values, redacted · saved at Save & verify)"
    ]


@pytest.mark.parametrize(
    "project_mode",
    [
        onboard_project.PROJECT_MODE_MACHINE_ONLY,
        onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN,
    ],
)
def test_runs_without_a_deploy_target_plan_no_hosting_row(project_mode: str) -> None:
    plan = _plan(
        project_mode=project_mode,
        hosting_choice=hosting_posture.POSTURE_UNDECIDED,
        reuse={},
    )

    assert all(
        step["action"] != hosting_posture.HOSTING_POSTURE_ACTION for step in plan["steps"]
    )
    assert onboard_project_modes.offers_hosting_credential(project_mode) is False


def test_reuse_detection_reads_the_machine_store(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / ".yoke"))
    directory = hosting.credential_dir("acme-app")
    directory.mkdir(parents=True)
    for key in (hosting.ACCESS_KEY_ID_KEY, hosting.SECRET_ACCESS_KEY_KEY):
        (directory / key).write_text("value\n", encoding="utf-8")

    detected = onboard_reuse_state.detect(
        cfg_path=tmp_path / ".yoke" / "config.json",
        env_name="prod",
        api_url="https://api.test",
        credential_source={"kind": "token_file", "path": ""},
        source={"kind": "token_file", "path": ""},
        project_inputs={"slug": "acme-app"},
        machine_github={"choice": "skip"},
    )

    assert detected["aws_admin"] is True


# --------------------------------------------------------------------------- #
# Review honesty
# --------------------------------------------------------------------------- #


def _review_plan(reuse: dict) -> dict:
    return {
        "project_mode": onboard_project.PROJECT_MODE_CREATE_REPO,
        "plan": {
            "reuse": reuse,
            "steps": [{"action": "set-active-env", "target": "prod"}],
        },
    }


def test_subtitle_names_the_secrets_already_saved() -> None:
    subtitle = review_steps._review_subtitle(
        _review_plan({"token_reference": True, "aws_admin": True}),
        machine_github_saved=False,
    )

    assert subtitle == review_steps.REVIEW_SAVED_SECRETS_SUBTITLE


def test_subtitle_keeps_its_promise_when_nothing_is_saved_yet() -> None:
    subtitle = review_steps._review_subtitle(
        _review_plan({}),
        machine_github_saved=False,
    )

    assert subtitle == review_steps.REVIEW_SUBTITLE


def test_subtitle_does_not_claim_a_token_that_is_not_saved() -> None:
    """One saved secret is not two; the promise must not over-claim."""
    subtitle = review_steps._review_subtitle(
        _review_plan({"aws_admin": True}),
        machine_github_saved=False,
    )

    assert subtitle == review_steps.REVIEW_SUBTITLE


def test_review_shows_already_saved_state_before_the_apply_plan() -> None:
    pytest.importorskip("textual")
    from textual.widgets import Static

    from yoke_cli.config import onboard_wizard_steps as steps

    widgets = steps.finish_body(
        _review_plan({"token_reference": True, "aws_admin": True}),
        problems=[],
        notes=[],
        machine_github_saved=False,
    )
    rendered = [str(w.render()) for w in widgets if isinstance(w, Static)]

    already = next(i for i, line in enumerate(rendered) if line.startswith("Already"))
    apply_group = next(
        i for i, line in enumerate(rendered) if line.startswith("Apply —")
    )
    assert already < apply_group

    # Done and pending read differently, and the heading renders exactly once.
    assert f"  ✔ {onboard_reuse_feedback.API_TOKEN_REUSE_LINE}" in rendered
    assert '  • Make "prod" your active environment' in rendered
    # The heading was emitted twice before; the review draws it once, at the top.
    assert rendered.count("Review what Yoke will save.") == 1
    assert rendered[0] == "Review what Yoke will save."


def _machine_lines(reuse: dict) -> list[str]:
    return onboard_reuse_feedback.grouped_lines_for_plan(_review_plan(reuse))["machine"]


def test_the_saved_token_is_named_as_a_secret_with_its_custody() -> None:
    """The line names what was saved and when, not the connection it belongs to."""
    assert _machine_lines({"connection": True, "token_reference": True}) == [
        onboard_reuse_feedback.API_TOKEN_REUSE_LINE
    ]
    # A token file recorded without a matching connection reads the same way.
    assert _machine_lines({"token_reference": True}) == [
        onboard_reuse_feedback.API_TOKEN_REUSE_LINE
    ]


def test_the_two_saved_secrets_are_the_whole_already_saved_block() -> None:
    """What the review promises above the plan is exactly what is on disk."""
    lines = _machine_lines(
        {"yoke_home": True, "token_reference": True, "aws_admin": True}
    )

    assert lines == [
        onboard_reuse_feedback.API_TOKEN_REUSE_LINE,
        "The aws-admin hosting credential (2 values, redacted · saved at "
        "Save & verify)",
    ]


def test_the_home_folder_is_not_claimed_next_to_a_saved_secret() -> None:
    """Creating ~/.yoke already happened with the first secret saved into it."""
    for reuse in ({"token_reference": True}, {"aws_admin": True}):
        assert "Yoke home folder already exists." not in _machine_lines(
            {"yoke_home": True, **reuse}
        )


def test_the_home_folder_is_named_when_nothing_else_implies_it() -> None:
    """With no saved secret to speak for it, the folder is news worth reporting."""
    assert _machine_lines({"yoke_home": True}) == ["Yoke home folder already exists."]


def test_other_machine_state_still_reports_beside_the_secrets() -> None:
    """Suppressing the folder line does not silence the honest ones around it."""
    lines = _machine_lines(
        {
            "yoke_home": True,
            "token_reference": True,
            "machine_github": True,
            "temp_root": True,
            "cache_dir": True,
        }
    )

    assert "GitHub App authorization is already connected." in lines
    assert "Runtime scratch and cache folders already exist." in lines
