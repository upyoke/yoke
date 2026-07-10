"""Exact-byte SVG golden gates — Project and Finish wizard screens.

Companion to :mod:`test_onboard_wizard_goldens` (PATH / Connect / GitHub); both
share the render-and-assert harness in :mod:`onboard_wizard_golden_support`. Each
gate renders the real wizard at a pinned virtual-terminal size, drives it to the
target Project- or Finish-step screen with stubbed data, and asserts the exported
SVG matches the committed golden. Regenerate after an approved copy change:

    YOKE_WIZARD_GOLDEN_UPDATE=1 pytest runtime/api/cli/

The catalog<->golden parity meta-test lives in the companion module and covers
the goldens both modules produce.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("textual")

from runtime.api.cli.onboard_wizard_golden_support import (  # noqa: E402
    FINISH_PLAN_EMPTY,
    FINISH_PLAN_FULL,
    OWNERS,
    assert_golden,
    make_app,
    render,
)
from yoke_cli.config import onboard_project  # noqa: E402
from yoke_cli.config import onboard_wizard_flow  # noqa: E402
from yoke_cli.config import project_git_transport  # noqa: E402
from yoke_cli.config.onboard_wizard_app import OnboardWizardApp  # noqa: E402


@pytest.fixture(autouse=True)
def _stub_source_branch(monkeypatch):
    # The clone-URL step probes the source's default branch with git ls-remote;
    # stub it so these render-only gates never shell out to git or hit the
    # fictional acme/widgets URL.
    monkeypatch.setattr(
        project_git_transport, "remote_default_branch",
        lambda url, token=None, github_web_url=None: "main",
    )


# --------------------------------------------------------------------------- #
# Project step (batch 3 + 4)
# --------------------------------------------------------------------------- #


def test_project_source_select() -> None:
    app = make_app()

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a._goto_project_mode()

    assert_golden("project_source_select", render(app, drive, title="yoke onboard · Project"))


def test_project_folder_input() -> None:
    app = make_app()

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a._on_project_mode(onboard_project.PROJECT_MODE_LOCAL_CHECKOUT)

    assert_golden("project_folder_input", render(app, drive, title="yoke onboard · Project"))


def test_project_name_input() -> None:
    app = make_app()

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a.result.project_mode = onboard_project.PROJECT_MODE_LOCAL_CHECKOUT
        a.result.project_checkout = "~/code/my-project"
        a._goto_slug()

    assert_golden("project_name_input", render(app, drive, title="yoke onboard · Project"))


def test_project_publish_prompt() -> None:
    app = make_app()

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a.result.project_mode = onboard_project.PROJECT_MODE_CREATE_REPO
        a.result.project_checkout = "~/code/my-project"
        a.result.project_slug = "my-project"
        a.result.project_name = "My Project"
        a._goto_publish_prompt()

    assert_golden("project_publish_prompt", render(app, drive, title="yoke onboard · Project"))


def test_project_owner_picker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(onboard_wizard_flow, "fetch_repo_owners", lambda *_a, **_k: OWNERS)
    app = make_app()

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a.result.project_publish_to_github = True
        a._show_owner_picker(OWNERS)

    assert_golden("project_owner_picker", render(app, drive, title="yoke onboard · Project"))


def test_project_repo_name() -> None:
    app = make_app()

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a.result.project_slug = "my-project"
        a._owner_lookup = {o.login: o for o in OWNERS}
        a._on_owner_pick("acme-inc")

    assert_golden("project_repo_name", render(app, drive, title="yoke onboard · Project"))


def test_project_branch_prefix_input() -> None:
    # The default-branch and issue-prefix entries render as TWO sequential
    # single-input views with distinct titles (onboard_wizard_flow `_after_repo`
    # -> `_after_branch`). This golden captures the first — the default-branch
    # input.
    app = make_app()

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a.result.project_slug = "my-project"
        a._after_repo("")

    assert_golden("project_branch_prefix_input", render(app, drive, title="yoke onboard · Project"))


def test_project_github_auth() -> None:
    app = make_app()

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a.result.project_slug = "my-project"
        a.result.project_github_repo = "acme-inc/my-project"
        a.result.project_public_item_prefix = "PROJ"
        # A verified machine App connection renders the connected-repo row.
        a.result.machine_github_verification = {"ok": True}
        a._after_prefix("PROJ")

    assert_golden("project_github_auth", render(app, drive, title="yoke onboard · Project"))


def test_project_clone_url_input() -> None:
    app = make_app()

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        # Clone now asks for the remote first (no machine token -> the
        # public/private split is skipped straight to the URL paste).
        a._on_project_mode(onboard_project.PROJECT_MODE_CLONE_REMOTE)

    assert_golden("project_clone_url_input", render(app, drive, title="yoke onboard · Project"))


def test_project_clone_folder() -> None:
    app = make_app(token=None)

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        # After the remote, the local folder defaults from the repo name
        # (~/code/widgets). Keep the app tokenless so this golden asserts the
        # clone-folder input rather than the async existing-project lookup.
        a.result.project_mode = onboard_project.PROJECT_MODE_CLONE_REMOTE
        a._after_remote("https://github.com/acme/widgets.git")

    assert_golden("project_clone_folder", render(app, drive, title="yoke onboard · Project"))


def test_project_clone_outcome() -> None:
    app = make_app()

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a.result.project_mode = onboard_project.PROJECT_MODE_CLONE_REMOTE
        a.result.project_remote_url = "https://github.com/acme/widgets.git"
        a._goto_clone_outcome()

    assert_golden("project_clone_outcome", render(app, drive, title="yoke onboard · Project"))


# --------------------------------------------------------------------------- #
# Finish step (batch 3)
# --------------------------------------------------------------------------- #


def test_finish_review_full() -> None:
    app = make_app(apply_report=lambda _kw: FINISH_PLAN_FULL)

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a._goto_finish()

    assert_golden("finish_review_full", render(app, drive, title="yoke onboard · Review"))


def test_finish_review_empty() -> None:
    app = make_app(apply_report=lambda _kw: FINISH_PLAN_EMPTY)

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a._goto_finish()

    assert_golden("finish_review_empty", render(app, drive, title="yoke onboard · Review"))


def test_finish_error() -> None:
    def _boom(_kw: dict[str, Any]) -> Any:
        raise RuntimeError("A custom API URL is required when the environment is Custom.")

    app = make_app(apply_report=_boom)

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a._goto_finish()

    assert_golden("finish_error", render(app, drive, title="yoke onboard · Review"))


def test_finish_apply_success() -> None:
    app = make_app()

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a.report_path = "~/.yoke/onboarding-runs/apply-reports/run-test.json"
        a._goto_apply_success()

    assert_golden("finish_apply_success", render(app, drive, title="yoke onboard · Review"))


def test_finish_applying() -> None:
    # The live Applying screen, rendered from a frozen step model (a fixed mix of
    # done / running / pending) so the status glyphs are deterministic.
    app = make_app()

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a._apply_steps = [
            {"step_id": "00-create-or-validate-dir",
             "action": "create-or-validate-dir", "target": "/home/.yoke",
             "label": "Create your Yoke home folder at ~/.yoke",
             "status": "done"},
            {"step_id": "01-set-active-env", "action": "set-active-env",
             "target": "stage", "label": 'Make "stage" your active environment',
             "status": "done"},
            {"step_id": "02-project-create-checkout",
             "action": "project-create-checkout", "target": "~/code/widget",
             "label": "Create the project at ~/code/widget", "status": "running"},
            {"step_id": "03-project-install-scaffold",
             "action": "project-install-scaffold", "target": "",
             "label": "Install the Yoke project scaffold (.yoke/)",
             "status": "pending"},
            {"step_id": "04-project-write-board-art",
             "action": "project-write-board-art", "target": "",
             "label": "Write your board art and initial BOARD.md",
             "status": "pending"},
        ]
        a._goto_applying()

    assert_golden("finish_applying", render(app, drive, title="yoke onboard · Review"))


def test_finish_apply_failure() -> None:
    # The in-TUI Apply-failure screen for a content collision (non-retryable):
    # real reason, report path, resume command, and recovery rows.
    app = make_app()

    async def drive(a: OnboardWizardApp, _pilot: Any) -> None:
        a.last_error = "beebauman/widget already exists and has content."
        a.failed_step = "07-project-create-checkout"
        a.report_path = "~/.yoke/onboarding-runs/apply-reports/run-test.json"
        a.resume_command = "yoke onboard"
        a._goto_apply_failure()

    assert_golden("finish_apply_failure", render(app, drive, title="yoke onboard · Review"))
