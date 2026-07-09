"""The "Develop Yoke itself" step transitions for the ``yoke onboard`` wizard.

A mixin composed alongside :class:`onboard_wizard_flow.WizardFlow` into
:class:`onboard_wizard_app.OnboardWizardApp`. It owns the source-dev-admin path:
verify the connected Yoke token reaches Yoke's own project, verify GitHub
authorization for Yoke's repo, then smart-detect an existing local Yoke
checkout (found -> use it; many -> pick; none -> point at one or clone). Each
failed check renders the recoverable error screen; success sets the
source-dev-admin project fields and routes to Finish, where ``_project_report``
maps the mode onto ``onboard_existing(operation="onboard.source-dev-admin")``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config import yoke_dev_access as dev_access
from yoke_cli.config import yoke_dev_detect as dev_detect
from yoke_cli.config.onboard_wizard_widgets import (
    STEP_PROJECT,
    SelectionRow,
)

# Slug/name/branch/prefix for the Yoke source checkout. The mode points at the
# existing Yoke repo, so these are fixed Yoke identifiers rather than
# user-entered metadata.
_YOKE_SLUG = dev_access.YOKE_PROJECT_SLUG
_YOKE_NAME = dev_access.YOKE_PROJECT_NAME
_YOKE_BRANCH = dev_access.YOKE_DEFAULT_BRANCH
_YOKE_PREFIX = dev_access.YOKE_PUBLIC_ITEM_PREFIX

# Picker value used to mean "none of the detected checkouts — clone Yoke".
_CLONE_YOKE = "clone-yoke"

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.onboard_wizard_app import _View


class _Shell(Protocol):  # pragma: no cover - structural typing only
    result: Any
    _preset_dev_checkout: str | None

    def _goto(self, view: "_View") -> None: ...
    def _selection_view(self, step, title, subtitle, rows, on_select) -> "_View": ...
    def _goto_input(self, step, title, subtitle, *, placeholder, on_done,
                    password: bool = False,
                    allow_placeholder: bool = True,
                    initial_value: str = "") -> None: ...
    def _goto_finish(self) -> None: ...
    def _run_checking(self, **kwargs) -> None: ...


class DevFlow:
    # ── Develop Yoke itself (source-dev-admin) ────────────

    def _start_dev_flow(self: _Shell) -> None:
        """Run the Yoke-project access check, the first of the two grants."""
        self._run_checking(
            step=STEP_PROJECT,
            title="Checking Yoke access.",
            message="Verifying this account can reach the Yoke project.",
            work=self._check_dev_yoke_access,
            on_success=lambda _result: self._goto_dev_github_check(),
            on_error=lambda exc: self._goto_dev_error(str(exc)),
            group="onboard-dev-yoke",
        )

    def _check_dev_yoke_access(self: _Shell) -> bool:
        try:
            token = dev_access.resolve_yoke_token(
                self.result.token, self.result.token_file,
            )
            if not token or not self.result.api_url:
                raise dev_access.YokeDevAccessError(
                    "This machine isn't connected to a Yoke control plane yet "
                    "— connect to your Yoke before developing Yoke."
                )
            if not dev_access.yoke_project_reachable(self.result.api_url, token):
                raise dev_access.YokeDevAccessError(
                    "This Yoke token can't reach the Yoke project — you need "
                    "access to develop Yoke."
                )
        except dev_access.YokeDevAccessError as exc:
            raise RuntimeError(str(exc)) from exc
        return True

    def _goto_dev_github_check(self: _Shell) -> None:
        """Second grant: GitHub authorization that can read Yoke's repo."""
        if self.result.machine_github_token:
            self._run_dev_github_check(self.result.machine_github_token)
            return
        self._goto_dev_error(
            "Developing Yoke requires GitHub App access to Yoke's repo. "
            "Connect GitHub after the App browser flow is available, then rerun onboarding."
        )

    def _after_dev_github_pat(self: _Shell, value: str) -> None:
        self.result.machine_github_token = value
        if not self.result.machine_github_api_url:
            self.result.machine_github_api_url = "https://api.github.com"
        self._run_dev_github_check(value)

    def _run_dev_github_check(self: _Shell, github_token: str) -> None:
        self._run_checking(
            step=STEP_PROJECT,
            title="Checking Yoke GitHub access.",
            message="Verifying GitHub authorization can read Yoke's repo.",
            work=lambda: self._check_dev_github_access(github_token),
            on_success=lambda _result: self._goto_dev_checkout(),
            on_error=lambda exc: self._goto_dev_error(str(exc)),
            group="onboard-dev-github",
        )

    def _check_dev_github_access(self: _Shell, github_token: str) -> bool:
        api_url = self.result.machine_github_api_url or "https://api.github.com"
        try:
            reachable = dev_access.github_can_reach_yoke_repo(api_url, github_token)
        except dev_access.YokeDevAccessError as exc:
            raise RuntimeError(str(exc)) from exc
        if not reachable:
            raise RuntimeError(
                "You need BOTH Yoke-project access and GitHub access to "
                "Yoke's repo to develop Yoke."
            )
        return True

    def _goto_dev_checkout(self: _Shell) -> None:
        """Third step: find an existing checkout, or offer to clone one."""
        if self._preset_dev_checkout:
            checkout = self._preset_dev_checkout
            self._preset_dev_checkout = None
            self._use_dev_checkout(checkout)
            return
        self._run_checking(
            step=STEP_PROJECT,
            title="Checking local checkouts.",
            message="Looking for an existing Yoke checkout on this machine.",
            work=dev_detect.detect_yoke_checkouts,
            on_success=self._show_dev_checkout,
            on_error=lambda exc: self._goto_dev_error(str(exc)),
            group="onboard-dev-checkout",
        )

    def _show_dev_checkout(self: _Shell, checkouts: Any) -> None:
        if len(checkouts) == 1:
            self._use_dev_checkout(str(checkouts[0]))
            return
        if not checkouts:
            self._goto_input(
                STEP_PROJECT, "Where is your Yoke checkout?",
                "Point at your local clone of Yoke, or paste a folder to clone into.",
                placeholder="~/code/yoke",
                allow_placeholder=False,
                on_done=self._use_dev_checkout,
            )
            return
        rows = [
            SelectionRow(str(path), str(path), "Yoke checkout")
            for path in checkouts
        ]
        rows.append(SelectionRow(_CLONE_YOKE, "None of these — clone Yoke",
                                 "into a new folder"))
        self._goto(self._selection_view(
            STEP_PROJECT, "Which Yoke checkout?",
            "Pick the local Yoke clone to develop in.",
            rows, self._on_dev_checkout_pick,
        ))

    def _on_dev_checkout_pick(self: _Shell, choice: str) -> None:
        if choice == _CLONE_YOKE:
            self._goto_input(
                STEP_PROJECT, "Where should Yoke be cloned?",
                "Yoke clones its repo into this new folder.",
                placeholder="~/code/yoke",
                allow_placeholder=False,
                on_done=self._use_dev_checkout,
            )
            return
        self._use_dev_checkout(choice)

    def _use_dev_checkout(self: _Shell, checkout: str) -> None:
        # Whether the folder already holds a Yoke checkout or is a fresh target
        # to clone Yoke into, the source-dev-admin onboarding takes the path
        # the same way — it reports new-local vs existing-local at apply.
        error = dev_detect.preflight_dev_checkout(checkout)
        if error is not None:
            self._goto_dev_error(error)
            return
        self.result.project_checkout = checkout
        self.result.project_slug = _YOKE_SLUG
        self.result.project_name = _YOKE_NAME
        self.result.project_default_branch = _YOKE_BRANCH
        self.result.project_public_item_prefix = _YOKE_PREFIX
        self._goto_finish()

    def _goto_dev_error(self: _Shell, message: str) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        self._goto(_View(STEP_PROJECT, lambda: steps.error_body(message)))


__all__ = ["DevFlow"]
