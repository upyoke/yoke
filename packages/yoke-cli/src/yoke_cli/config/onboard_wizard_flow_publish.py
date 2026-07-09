"""Publish-to-GitHub step transitions for the ``yoke onboard`` wizard.

A mixin composed alongside :class:`onboard_wizard_flow.WizardFlow` into
:class:`onboard_wizard_app.OnboardWizardApp`. It owns the "Also publish to
GitHub?" follow-up offered for the create-new and existing-folder project modes
(:data:`onboard_wizard_flow.PUBLISH_MODES`): the publish yes/no choice, the
GitHub App availability gate, and the owner-picker + repo-name screens. Each
answer is recorded onto ``self.result`` and routed back into the shared project step
(``_after_repo`` -> ``_after_branch``). It holds no report-assembly logic; the
PublishRequest it populates is assembled in :class:`onboard_wizard.WizardResult`.

The make-it-mine clone outcome reuses ``_goto_owner_picker`` + ``_after_repo``
from here, so the owner-picker screens serve both the fresh-publish and the
clone re-home paths.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from yoke_cli.config import onboard_input_validation as input_validation
from yoke_cli.config import onboard_project
from yoke_cli.config import onboard_wizard_flow
from yoke_cli.config import onboard_wizard_project_screens as project_screens
from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config.onboard_wizard_widgets import STEP_PROJECT
from yoke_cli.config.project_publish_support import has_remote

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.onboard_wizard_app import _View


class _Shell(Protocol):  # pragma: no cover - structural typing only
    result: Any

    def _goto(self, view: "_View") -> None: ...
    def _selection_view(self, step, title, subtitle, rows, on_select) -> "_View": ...
    def _goto_input(self, step, title, subtitle, *, placeholder, on_done,
                    password: bool = False,
                    allow_placeholder: bool = True,
                    validate=None,
                    initial_value: str = "") -> None: ...
    def _after_branch(self, value: str) -> None: ...
    def _run_checking(self, **kwargs) -> None: ...


class PublishFlow:
    # ── Publish to GitHub follow-up (existing-folder + create-new) ──────────

    def _goto_publish_prompt(self: _Shell) -> None:
        # Auto-skip the publish offer when the checkout already points at a
        # remote — re-homing an existing remote is a separate capability.
        checkout = self.result.project_checkout
        if checkout and has_remote(Path(checkout).expanduser()):
            self.result.project_keep_existing_remote = True
            self._after_repo("")
            return
        self._goto(self._selection_view(
            STEP_PROJECT,
            "Also publish to GitHub?",
            "Yoke creates the repo through the Yoke GitHub App and connects it as your remote.",
            project_screens.PUBLISH_ROWS, self._on_publish_choice,
        ))

    def _on_publish_choice(self: _Shell, choice: str) -> None:
        if choice != project_screens.PUBLISH_YES:
            self.result.project_publish_to_github = False
            if getattr(self, "_publish_user_token_only", False):
                self.result.machine_github_token = None
                self.result.machine_github_api_url = None
                self.result.machine_github_token_source_kind = None
                self._publish_user_token_only = False
            self._after_repo("")
            return
        self.result.project_publish_to_github = True
        self._goto_publish_unavailable()

    def _goto_publish_unavailable(self: _Shell) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        def _select(choice: str) -> None:
            if choice == "backlog":
                self.result.project_publish_to_github = False
                self._after_repo("")
                return
            self._goto_publish_prompt()

        self._goto(_View(
            STEP_PROJECT,
            lambda: steps.verification_body(
                "GitHub App publishing is not available here yet.",
                (
                    "This setup flow no longer accepts manual GitHub credentials. "
                    "Keep the project local or connect GitHub after the App flow is available."
                ),
                [
                    "No repository will be created on GitHub during this run.",
                    "The project can still be set up locally.",
                ],
                steps.GITHUB_APP_UNAVAILABLE_ROWS,
                ok=False,
            ),
            _select,
        ))

    def _machine_can_publish(self: _Shell) -> bool:
        """True only when connected GitHub publish ability is confirmed True.

        Reads ``capability.can_publish`` (create AND push-to-a-new-repo)
        recorded by verification. Anything other than a confirmed True is
        treated as cannot-publish so the doomed create+push never runs.
        """
        verification = self.result.machine_github_verification
        if not isinstance(verification, dict):
            return False
        capability = verification.get("capability")
        if not isinstance(capability, dict):
            return False
        return capability.get("can_publish") is True

    def _goto_publish_cannot_create(self: _Shell) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        def _ack(_choice: str) -> None:
            self.result.project_publish_to_github = False
            self._after_repo("")  # no repo: drop adoption, keep it local

        self._goto(_View(
            STEP_PROJECT,
            lambda: steps.verification_body(
                "GitHub authorization can't publish a new repo.",
                self._cannot_publish_reason(),
                [],
                steps.VERIFY_OK_ROWS,
                ok=False,
            ),
            _ack,
        ))

    def _cannot_publish_reason(self: _Shell) -> str:
        """Explain whether the block is a create gap or a push-to-new-repo gap."""
        verification = self.result.machine_github_verification
        capability = (
            verification.get("capability") if isinstance(verification, dict) else None
        )
        can_create = capability.get("can_create") if isinstance(capability, dict) else None
        tail = (
            " Create the repo on GitHub first and make sure GitHub authorization "
            "has write access to it, and then re-run yoke onboard."
        )
        if can_create is True:
            return (
                "GitHub authorization is scoped to selected repositories, so it "
                "can't publish a brand-new repo in one step." + tail
            )
        return "GitHub authorization can't create a repo it can also push to." + tail

    def _goto_publish_github_auth(self: _Shell) -> None:
        self._goto_publish_unavailable()

    def _after_publish_github_auth(self: _Shell, value: str) -> None:
        self._goto_publish_unavailable()

    def _goto_publish_github_auth_error(self: _Shell, message: str) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        def _retry(choice: str) -> None:
            if choice == "retry":
                self._goto_publish_github_auth()
                return
            # "Back": abandon publishing and keep the project local.
            self.result.project_publish_to_github = False
            self._after_repo("")

        self._goto(_View(
            STEP_PROJECT,
            lambda: steps.verification_body(
                "GitHub authorization could not be verified.",
                message,
                ["Check GitHub App access and network availability."],
                steps.VERIFY_RETRY_ROWS,
                ok=False,
            ),
            _retry,
        ))

    def _goto_owner_picker(self: _Shell) -> None:
        self._run_checking(
            step=STEP_PROJECT,
            title="Checking GitHub owners.",
            message="Finding where GitHub authorization can create the repo.",
            work=self._fetch_repo_owners,
            on_success=self._show_owner_picker,
            on_error=self._goto_owner_picker_error,
            group="onboard-owner-picker",
        )

    def _fetch_repo_owners(self: _Shell) -> list:
        return onboard_wizard_flow.fetch_repo_owners(
            self.result.machine_github_api_url or "https://api.github.com",
            self.result.machine_github_token or "",
        )

    def _show_owner_picker(self: _Shell, owners: Any) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        self._owner_lookup = {o.login: o for o in owners}
        self._goto(_View(
            STEP_PROJECT,
            lambda: project_screens.owner_picker_body(owners),
            self._on_owner_pick,
        ))

    def _goto_owner_picker_error(self: _Shell, exc: BaseException) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        self._goto(_View(
            STEP_PROJECT,
            lambda: steps.verification_body(
                "Couldn't load GitHub owners.",
                str(exc),
                ["Check GitHub App access, GitHub availability, and the network."],
                steps.PROBE_RETRY_ROWS,
                ok=False,
            ),
            self._on_owner_picker_error,
        ))

    def _on_owner_picker_error(self: _Shell, choice: str) -> None:
        if choice == "retry":
            self._goto_owner_picker()
            return
        self.result.project_publish_to_github = False
        self._after_repo("")

    def _on_owner_pick(self: _Shell, login: str) -> None:
        self.result.project_publish_owner = login
        self.result.project_publish_owner_login = next(
            (o.login for o in self._owner_lookup.values() if o.kind == "user"),
            login,
        )
        visibility = "private" if self.result.project_publish_private else "public"
        self._goto_input(
            STEP_PROJECT, "Name the repo.",
            f"Created as {login}/… · {visibility}.",
            placeholder=self.result.project_slug or "project",
            on_done=self._after_repo_name,
        )

    def _after_repo_name(self: _Shell, value: str) -> None:
        self.result.project_publish_repo_name = value
        self.result.project_github_repo = f"{self.result.project_publish_owner}/{value}"
        self._after_repo(self.result.project_github_repo)

    def _after_repo(self: _Shell, value: str) -> None:
        self.result.project_github_repo = value or None
        if not value:
            # No repo means no GitHub adoption. Clear any adoption + token a
            # prior back-nav visit set so declining publish can't leave a stale
            # App binding that raises "adoption requires --github-repo"
            # at apply.
            self.result.project_github_adoption = None
            self.result.project_github_token = None
        # The default branch is a property of the source for any clone-of-existing
        # outcome (just-clone / make-it-mine / fork) — it is detected at the URL
        # step, not picked. Skip the prompt and carry the detected branch (or the
        # plain fallback when detection failed); the prompt stays only for
        # creating a brand-new empty repo, where "main" is a real choice.
        if self.result.project_mode in onboard_project.PROJECT_REMOTE_MODES:
            self._after_branch(
                self.result.project_source_default_branch
                or onboard_project.DEFAULT_NEW_REPO_BRANCH
            )
            return
        self._goto_input(
            STEP_PROJECT, "Pick the default branch.",
            "Yoke fills this in for you — change it if you like.",
            placeholder=onboard_project.DEFAULT_NEW_REPO_BRANCH,
            on_done=self._after_branch,
            validate=input_validation.validate_branch,
        )


__all__ = ["PublishFlow"]
