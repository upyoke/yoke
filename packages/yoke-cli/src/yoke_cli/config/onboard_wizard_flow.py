"""Step transitions for the ``yoke onboard`` wizard.

A mixin consumed by :class:`onboard_wizard_app.OnboardWizardApp`. It owns the
GitHub -> Project -> Finish progression (the Connect step lives in
:class:`onboard_wizard_flow_connect.ConnectFlow`): each handler records one
answer onto ``self.result`` and routes to the next view through the shell's
``_goto`` / ``_goto_input`` / ``_selection_view`` primitives. It holds no
Textual plumbing and no report-assembly logic — only the decision graph.

The machine GitHub step runs before the project step so repo binding can use
the machine's GitHub App authorization once that flow is connected.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoke_cli.config import (
    onboard_wizard_existing_project_detected as existing_project_detected,
)
from yoke_cli.config import onboard_github_copy
from yoke_cli.config import onboard_input_validation as input_validation
from yoke_cli.config import onboard_project
from yoke_cli.config.onboard_error_friendly import friendly_permission_error

from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config.onboard_wizard import github_connected
from yoke_cli.config.onboard_wizard_project_github import ProjectGithubAccessFlow
from yoke_cli.config.onboard_wizard_project_identity_flow import (
    PUBLISH_MODES as PUBLISH_MODES,
    ProjectIdentityFlow,
)
from yoke_cli.config.onboard_wizard_existing_project_recovery import (
    ExistingProjectLookupRecoveryFlow,
)
from yoke_cli.config.onboard_wizard_finish_flow import FinishBodyFlow
from yoke_cli.config.onboard_wizard_stored_project import StoredProjectFlow
from yoke_cli.config.onboard_wizard_widgets import STEP_FINISH, STEP_PROJECT
from yoke_cli.config.project_publish_support import is_existing_project_dir
from yoke_cli.config.onboard_wizard_flow_support import WizardShell as _Shell
from yoke_cli.config.onboard_wizard_flow_support import (
    fetch_repo_owners as _fetch_repo_owners,
)


def fetch_repo_owners(api_url: str, token: str) -> list:
    """Owner-list seam that tests patch instead of calling GitHub."""
    return _fetch_repo_owners(api_url, token)


class WizardFlow(
    ProjectIdentityFlow,
    ExistingProjectLookupRecoveryFlow,
    existing_project_detected.ExistingProjectDetectedFlow,
    FinishBodyFlow,
    ProjectGithubAccessFlow,
    StoredProjectFlow,
):
    # ── Project step ────────────────────────────────────────

    def _goto_project_mode(self: _Shell) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        if self._project_mode_preset and not self._project_preset_attempted:
            self._project_preset_attempted = True
            self._preserve_project_fields_once = True
            self._on_project_mode(self.result.project_mode)
            return
        if self._stored_project_checkouts and not self._stored_project_attempted:
            self._stored_project_attempted = True
            self._goto_stored_project_picker()
            return
        view = _View(STEP_PROJECT, steps.project_mode_body, self._on_project_mode)
        self._project_mode_view = view
        self._goto(view)

    def _on_project_mode(self: _Shell, mode: str) -> None:
        if not getattr(self, "_preserve_project_fields_once", False):
            steps.reset_project_fields(self.result)
        self._preserve_project_fields_once = False
        self.result.project_mode = mode
        if mode == onboard_project.PROJECT_MODE_MACHINE_ONLY:
            self._goto_hosting()
            return
        self._check_project_git(mode)

    def _after_project_git_ready(self: _Shell, mode: str) -> None:
        if mode == onboard_project.PROJECT_MODE_EDIT_YOKE_SOURCE:
            # Edit Yoke source is public: choose or clone a checkout, with no
            # official project or canonical-repository grant.
            self._start_dev_flow()
            return
        if mode in onboard_project.PROJECT_REMOTE_MODES:
            # Clone asks for the remote first; the local folder then defaults
            # from the repo name (~/code/<repo>) and is collected by the clone
            # flow after the URL, not here.
            self._goto_clone_visibility()  # CloneFlow mixin: public/private split
            return
        if (
            mode == onboard_project.PROJECT_MODE_LOCAL_CHECKOUT
            and self._pending_stored_project_checkout
        ):
            checkout = self._pending_stored_project_checkout
            self._pending_stored_project_checkout = None
            self._after_local_checkout_source(checkout)
            return
        # Folder-prompt copy: create-new makes a fresh folder; local-checkout
        # points at code already on disk.
        if mode == onboard_project.PROJECT_MODE_CREATE_REPO:
            title, subtitle = (
                "Name your new project folder.",
                "Where should Yoke create it? It makes the folder and a git repo.",
            )
        else:
            title, subtitle = (
                "Point at your project folder.",
                "Where's the code on this machine? Yoke makes it a git repo if it isn't.",
            )
        # Validate inline: a plain file or an unwritable parent is rejected here,
        # not at Apply. An existing non-empty dir is fine — create-new redirects
        # it to adopt-the-existing-folder in _after_checkout.
        self._goto_input(
            STEP_PROJECT,
            title,
            subtitle,
            placeholder="~/code/my-project",
            on_done=self._after_checkout,
            validate=input_validation.validate_create_target_folder,
        )

    def _after_checkout(self: _Shell, value: str) -> None:
        mode = self.result.project_mode
        steps.reset_project_fields(self.result)
        self.result.project_mode = mode
        self.result.project_checkout = value
        # "Create a new project" pointed at a folder that already holds code is
        # really the existing-folder case. Adopt it instead of creating over it:
        # switch modes (so Apply onboards the existing checkout and the review
        # reads "Set up" not "Create") and tell the user what happened.
        if (
            self.result.project_mode == onboard_project.PROJECT_MODE_CREATE_REPO
            and is_existing_project_dir(Path(value).expanduser())
        ):
            self.result.project_mode = onboard_project.PROJECT_MODE_LOCAL_CHECKOUT
            self._goto_existing_dir_redirect(value)
            return
        self._after_local_checkout_source(value)

    def _goto_existing_dir_redirect(self: _Shell, path: str) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        self._goto(
            _View(
                STEP_PROJECT,
                lambda: steps.verification_body(
                    "That folder already exists.",
                    f"Yoke will set up {path} as an existing project instead of "
                    "creating a new one.",
                    [],
                    steps.VERIFY_OK_ROWS,
                    ok=True,
                ),
                lambda _choice: self._after_local_checkout_source(path),
            )
        )

    # ── Branch / prefix / project-GitHub auth (shared tail) ─────────────────

    def _after_prefix(self: _Shell, value: str) -> None:
        self.result.project_public_item_prefix = value
        if not self.result.project_github_repo:
            self._goto_board_art()
            return
        if self._route_future_project_github_binding():
            return
        # Existing-repo rows require a connected machine App authorization.
        if github_connected(self.result):
            rows = steps.PROJECT_GITHUB_ROWS
        else:
            rows = steps.PROJECT_GITHUB_ROWS_NO_MACHINE
        self._goto(
            self._selection_view(
                STEP_PROJECT,
                onboard_github_copy.PROJECT_GITHUB_PROMPT_TITLE,
                onboard_github_copy.PROJECT_GITHUB_PROMPT_SUBTITLE,
                rows,
                self._on_project_github,
            )
        )

    # ── Finish step ─────────────────────────────────────────

    def _goto_finish(self: _Shell) -> None:
        self._run_checking(
            step=STEP_FINISH,
            title="Preparing Review.",
            message="Checking the write plan and final preflight.",
            work=self._build_review_model,
            on_success=self._show_finish,
            on_error=self._goto_finish_error,
            group="onboard-review",
        )

    def _build_review_model(self) -> dict[str, Any]:
        try:
            plan = self._apply_report(
                self.result.build_report_kwargs(apply=False, check_identity=False)
            )
        except Exception as exc:  # noqa: BLE001 - clean error view, never a traceback
            raise RuntimeError(friendly_permission_error(str(exc))) from exc
        # Consolidated pre-flight: re-check the target, token, and repo-name one
        # last time so the Review screen surfaces every remaining problem at once
        # and Apply is guarded until they clear — the safety net behind "Nothing
        # is written until you choose Apply". The same pass yields advisory notes
        # (e.g. an existing empty repo Apply will reuse).
        # Stash the previewed plan so the live Applying screen renders the exact
        # same step rows the report tracks.
        checks = self._review_preflight()
        return {"plan": plan if isinstance(plan, dict) else {}, "checks": checks}

    def _show_finish(self: _Shell, model: Any) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        checks = model.get("checks") if isinstance(model, dict) else None
        self._review_plan = model.get("plan") if isinstance(model, dict) else {}
        self._review_show_all = False
        self._review_problems = list(getattr(checks, "problems", []) or [])
        self._review_notes = list(getattr(checks, "notes", []) or [])
        self._goto(_View(STEP_FINISH, self._build_finish, self._on_confirm))

    def _goto_finish_error(self: _Shell, exc: BaseException) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        self._goto(
            _View(
                STEP_FINISH,
                lambda: steps.error_body(str(exc)),
            )
        )

    def _review_preflight(self: _Shell):
        """Run the Review pre-flight once, returning problems and advisory notes.

        Single seam over :func:`onboard_preflight.preflight` so tests stub one
        method; the live wizard wires the real network probes.
        """
        from yoke_cli.config import onboard_preflight

        return onboard_preflight.preflight(
            self.result, probes=onboard_preflight.default_probes()
        )

    def _on_confirm(self, choice: str) -> None:
        if choice == "show-all":
            self._review_show_all = not getattr(self, "_review_show_all", False)
            self._render_current()
            return
        if choice == "back":
            # Pre-flight blocked Apply: step back to the offending step so the
            # user can correct it, rather than quitting the wizard.
            import asyncio

            asyncio.ensure_future(self.action_back())
            return
        if choice != "apply":
            self.cancelled = True
            self.exit_code = 0
            self.exit()
            return
        # Apply runs off the event loop with a live Applying screen — see
        # ApplyFlow (onboard_wizard_flow_apply) for the worker + result screens.
        self._start_apply()


__all__ = ["WizardFlow"]
