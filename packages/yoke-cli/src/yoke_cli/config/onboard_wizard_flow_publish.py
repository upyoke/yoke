"""Publish-to-GitHub step transitions for the ``yoke setup`` wizard.

A mixin composed alongside :class:`onboard_wizard_flow.WizardFlow` into
:class:`onboard_wizard_app.OnboardWizardApp`. It owns the "Also publish to
GitHub?" follow-up offered for the create-new and existing-folder project modes
(:data:`onboard_wizard_flow.PUBLISH_MODES`): the publish yes/no choice, the
GitHub App availability gate, and the owner-picker + repo-name screens. Each
answer is recorded onto ``self.result`` and routed back into the shared project step
(``_after_repo`` -> ``_after_prefix``). It holds no report-assembly logic; the
PublishRequest it populates is assembled in :class:`onboard_wizard.WizardResult`.

The make-it-mine clone outcome reuses ``_goto_owner_picker`` + ``_after_repo``
from here, so the owner-picker screens serve both the fresh-publish and the
clone re-home paths.
"""

from __future__ import annotations


from yoke_cli.config import setup_browser
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from yoke_contracts import github_origin
from yoke_cli.config import onboard_input_validation as input_validation
from yoke_cli.config import onboard_local_checkout_identity
from yoke_cli.config import onboard_wizard_flow
from yoke_cli.config import onboard_wizard_project_screens as project_screens
from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config.onboard_wizard import github_connected
from yoke_cli.config.onboard_wizard_github_state import (
    endpoint_pair,
    user_access_token,
)
from yoke_cli.config.onboard_wizard_widgets import STEP_PROJECT
from yoke_cli.config.project_publish_support import has_remote
from yoke_cli.config.setup_prompt import TONE_ERROR, SetupPrompt

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.onboard_wizard_state import _View


class _Shell(Protocol):  # pragma: no cover - structural typing only
    result: Any

    def _goto(self, view: "_View") -> None: ...
    def _selection_view(self, key, step, title, subtitle, rows, on_select) -> "_View": ...
    def _goto_input(
        self,
        key,
        step,
        title,
        subtitle,
        *,
        placeholder,
        on_done,
        password: bool = False,
        allow_placeholder: bool = True,
        validate=None,
        initial_value: str = "",
    ) -> None: ...
    def _after_prefix(self, value: str) -> None: ...
    def _run_checking(self, **kwargs) -> None: ...
    def _step_back(self) -> None: ...


class PublishFlow:
    # ── Publish to GitHub follow-up (existing-folder + create-new) ──────────

    def _goto_publish_prompt(self: _Shell) -> None:
        # Auto-skip the publish offer when the checkout already points at a
        # remote — re-homing an existing remote is a separate capability.
        checkout = self.result.project_checkout
        if checkout and has_remote(Path(checkout).expanduser()):
            intended = str(self.result.project_github_repo or "")
            if intended:
                try:
                    onboard_local_checkout_identity.require_matching_origin(
                        checkout,
                        github_repo=intended,
                        web_url=endpoint_pair(self.result).web.base_url,
                    )
                except RuntimeError as exc:
                    self._goto_publish_origin_mismatch(exc)
                    return
            self.result.project_keep_existing_remote = True
            # Keep the already-detected canonical GitHub identity. Clearing it
            # here made the later App-binding step disappear even though the
            # checkout had a usable origin.
            self._after_repo(self.result.project_github_repo or "")
            return
        self._goto(
            self._selection_view(
                "project.publish",
                STEP_PROJECT,
                "Also publish to GitHub?",
                "Yoke creates the repo through the Yoke GitHub App and connects it as your remote.",
                project_screens.PUBLISH_ROWS,
                self._on_publish_choice,
                initial=0 if github_connected(self.result) else 1,
            )
        )

    def _goto_publish_origin_mismatch(self: _Shell, exc: BaseException) -> None:
        from yoke_cli.config.onboard_wizard_state import _View

        self._goto(
            _View(
                SetupPrompt(
                    key="project.publish_origin_mismatch",
                    step=STEP_PROJECT,
                    title="Checkout origin changed.",
                    message=str(exc),
                    detail_lines=tuple(["Repair the checkout origin, then retry the check."]),
                    choices=tuple(steps.PROBE_RETRY_ROWS),
                    tone=TONE_ERROR,
                ),
                self._on_publish_origin_mismatch,
            )
        )

    def _on_publish_origin_mismatch(self: _Shell, choice: str) -> None:
        if choice == "retry":
            if getattr(self, "_history", None):
                self._history.pop()
            self._goto_publish_prompt()
            return
        self._step_back()

    def _on_publish_choice(self: _Shell, choice: str) -> None:
        if choice != project_screens.PUBLISH_YES:
            self.result.project_publish_to_github = False
            self._after_repo("")
            return
        self.result.project_publish_to_github = True
        self.result.project_publish_create_repository = True
        self.result.project_publish_repository_id = None
        self.result.project_publish_installation_id = None
        if self._machine_can_publish():
            self._goto_owner_picker()
            return
        self._open_repository_creation_page()

    def _open_repository_creation_page(self: _Shell) -> None:
        url = endpoint_pair(self.result).new_repository_url()

        def completed(browser):
            self._manual_repository_url = url
            self._manual_repository_opened = browser.opened
            self._manual_repository_reason = browser.reason
            self._goto_publish_cannot_create()

        setup_browser.open_in_wizard(self, url, step=STEP_PROJECT, on_success=completed)

    def _machine_can_publish(self: _Shell) -> bool:
        """Whether a connected installation grants optional Administration."""
        if not github_connected(self.result):
            return False
        try:
            if endpoint_pair(self.result).deployment_kind != "github_cloud":
                return False
        except github_origin.GitHubApiOriginError:
            return False
        from yoke_cli.config import machine_config

        config = machine_config.github_config(self.result.config_path)
        return any(
            isinstance(raw, dict)
            and not raw.get("suspended")
            and raw.get("repository_selection") == "all"
            and isinstance(raw.get("permissions"), dict)
            and raw["permissions"].get("administration") == "write"
            for raw in config.get("installations") or []
        )

    def _cannot_publish_reason(self: _Shell) -> str:
        """Explain whether the block is a create gap or a push-to-new-repo gap."""
        if github_connected(self.result):
            return (
                "No non-suspended Yoke GitHub App installation grants the optional "
                "Administration permission and all-repositories access needed "
                "for one-step repo creation."
            )
        return "Connect the Yoke GitHub App before publishing."

    def _goto_owner_picker(
        self: _Shell,
        *,
        replace_current: bool = False,
    ) -> None:
        self._run_checking(
            step=STEP_PROJECT,
            title="Checking GitHub owners.",
            message="Finding where GitHub authorization can create the repo.",
            work=self._fetch_repo_owners,
            on_success=self._show_owner_picker,
            on_error=self._goto_owner_picker_error,
            group="onboard-owner-picker",
            blocks_quit=True,
            replace_current=replace_current,
        )

    def _fetch_repo_owners(self: _Shell) -> list:
        from yoke_cli.config import machine_config

        owners = onboard_wizard_flow.fetch_repo_owners(
            self.result.machine_github_api_url or github_origin.DEFAULT_GITHUB_API_URL,
            user_access_token(self.result) or "",
        )
        authenticated = next(
            (owner.login for owner in owners if owner.kind == "user"),
            "",
        )
        if not authenticated:
            raise RuntimeError(
                "GitHub did not identify the authenticated repository owner"
            )
        self._authenticated_github_login = authenticated
        config = machine_config.github_config(self.result.config_path)
        allowed = {
            str(row.get("account_login") or "").casefold()
            for row in config.get("installations") or []
            if isinstance(row, dict)
            and not row.get("suspended")
            and row.get("repository_selection") == "all"
            and isinstance(row.get("permissions"), dict)
            and row["permissions"].get("administration") == "write"
        }
        return [owner for owner in owners if owner.login.casefold() in allowed]

    def _show_owner_picker(self: _Shell, owners: Any) -> None:
        from yoke_cli.config.onboard_wizard_state import _View

        if not owners:
            self._open_repository_creation_page()
            return
        authenticated = next(
            (owner.login for owner in owners if owner.kind == "user"),
            "",
        )
        if authenticated:
            self._authenticated_github_login = authenticated
        self._owner_lookup = {o.login.casefold(): o for o in owners}
        prompt = project_screens.owner_picker_prompt(owners)
        self._goto(_View(
            prompt,
            self._on_owner_pick,
            lambda: project_screens.searchable_picker_body(prompt),
        ))

    def _goto_owner_picker_error(self: _Shell, exc: BaseException) -> None:
        from yoke_cli.config.onboard_wizard_state import _View

        self._goto(
            _View(
                SetupPrompt(
                    key="project.owner_picker_error",
                    step=STEP_PROJECT,
                    title="Couldn't load GitHub owners.",
                    message=str(exc),
                    detail_lines=tuple(["Check GitHub App access, GitHub availability, and the network."]),
                    choices=tuple(steps.PROBE_RETRY_ROWS),
                    tone=TONE_ERROR,
                ),
                self._on_owner_picker_error,
            )
        )

    def _on_owner_picker_error(self: _Shell, choice: str) -> None:
        if choice == "retry":
            self._goto_owner_picker(replace_current=True)
            return
        self._step_back()

    def _on_owner_pick(self: _Shell, login: str) -> None:
        selected = self._owner_lookup.get(login.casefold())
        authenticated = str(getattr(self, "_authenticated_github_login", "") or "")
        if selected is None or not authenticated:
            self._goto_owner_picker_error(
                RuntimeError("GitHub owner selection changed; reload the owner list")
            )
            return
        self.result.project_publish_owner = selected.login
        self.result.project_publish_owner_login = authenticated
        visibility = "private" if self.result.project_publish_private else "public"
        self._goto_input(
            "project.publish_repo_name",
            STEP_PROJECT,
            "Name the repo.",
            f"Created as {selected.login}/… · {visibility}.",
            placeholder=self.result.project_slug or "project",
            on_done=self._after_repo_name,
            validate=input_validation.validate_repository_name,
        )

    def _after_repo_name(self: _Shell, value: str) -> None:
        self.result.project_publish_create_repository = True
        self.result.project_publish_repository_id = None
        self.result.project_publish_installation_id = None
        self.result.project_publish_repo_name = value
        self.result.project_github_repo = f"{self.result.project_publish_owner}/{value}"
        self._after_repo(self.result.project_github_repo)

    def _after_repo(self: _Shell, value: str) -> None:
        self.result.project_github_repo = value or None
        if not value:
            # No repo means no GitHub adoption. Clear any adoption that a
            # prior back-nav visit set so declining publish can't leave a stale
            # App binding that raises "adoption requires --github-repo"
            # at apply.
            self.result.project_github_adoption = None
            self.result.project_github_adoption_preserve = False
        self._after_prefix(self.result.project_public_item_prefix or "")


__all__ = ["PublishFlow"]
