"""Project identity, existing-project lookup, and combined details form."""

from __future__ import annotations

from typing import Any

from yoke_cli.config import existing_project_lookup
from yoke_cli.config import onboard_existing_project
from yoke_cli.config import onboard_local_checkout_identity
from yoke_cli.config import onboard_project
from yoke_cli.config import onboard_wizard_board_art_apply
from yoke_cli.config import onboard_wizard_github_state
from yoke_cli.config import onboard_wizard_project_details as project_details
from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config import yoke_token_verify
from yoke_cli.config.onboard_destinations import DESTINATION_LOCAL
from yoke_cli.config.onboard_wizard import github_connected
from yoke_cli.config.onboard_wizard_flow_support import WizardShell as _Shell
from yoke_cli.config.onboard_wizard_widgets import STEP_PROJECT
from yoke_cli.config.project_github_adoption import GITHUB_ADOPTION_DISABLED

PUBLISH_MODES = (
    onboard_project.PROJECT_MODE_CREATE_REPO,
    onboard_project.PROJECT_MODE_LOCAL_CHECKOUT,
)


class ProjectIdentityFlow:
    """Resolve project identity before routing into publish or board art."""

    def _after_local_checkout_source(self: _Shell, value: str) -> None:
        try:
            remote, web_url = onboard_local_checkout_identity.inspect(
                self.result,
                value,
            )
        except RuntimeError as exc:
            self._goto_existing_project_lookup_error(
                exc,
                retry=lambda: self._after_local_checkout_source(value),
            )
            return
        try:
            local_ref = existing_project_lookup.find_local_project_reference(
                value,
                config_path=self.result.config_path,
            )
        except existing_project_lookup.ExistingProjectLookupError as exc:
            self._goto_existing_project_lookup_error(
                exc,
                retry=lambda: self._after_local_checkout_source(value),
            )
            return
        if local_ref is not None:
            self._lookup_recorded_project(local_ref, value)
            return
        if not remote or not self.result.project_github_repo:
            self._goto_project_details()
            return
        token = self._yoke_token_for_project_lookup()
        if not token:
            self._goto_project_details()
            return
        self._run_checking(
            step=STEP_PROJECT,
            title="Checking Yoke project.",
            message="Looking for an existing project for this repo.",
            work=lambda: existing_project_lookup.find_by_github_repo(
                api_url=self.result.api_url,
                token=token,
                github_repo=remote,
                web_url=web_url,
            ),
            on_success=lambda project: self._after_existing_project_lookup(
                project,
                match_source=existing_project_lookup.MATCH_SOURCE_GITHUB_REPO,
                local_source=None,
            ),
            on_error=lambda exc: self._goto_existing_project_lookup_error(
                exc,
                retry=lambda: self._after_local_checkout_source(value),
            ),
            group="onboard-existing-project",
        )

    def _lookup_recorded_project(self: _Shell, local_ref: Any, value: str) -> None:
        if self.result.destination == DESTINATION_LOCAL:
            self._run_checking(
                step=STEP_PROJECT,
                title="Checking local Yoke project.",
                message=(
                    f"Verifying project {local_ref.project_id} from "
                    f"{local_ref.source} in the local universe."
                ),
                work=lambda: existing_project_lookup.find_local_by_project_id(
                    config_path=self.result.config_path,
                    project_id=local_ref.project_id,
                ),
                on_success=lambda project: self._after_existing_project_lookup(
                    project,
                    match_source=existing_project_lookup.MATCH_SOURCE_LOCAL_CHECKOUT,
                    local_source=local_ref.source,
                ),
                on_error=lambda exc: self._goto_existing_project_lookup_error(
                    exc,
                    retry=lambda: self._after_local_checkout_source(value),
                    local_destination=True,
                ),
                group="onboard-existing-project",
            )
            return
        token = self._yoke_token_for_project_lookup()
        if not token:
            self._goto_existing_project_lookup_error(
                existing_project_lookup.ExistingProjectLookupError(
                    "couldn't read the Yoke API token to verify the local "
                    f"project id from {local_ref.source}"
                ),
                retry=lambda: self._after_local_checkout_source(value),
            )
            return
        self._run_checking(
            step=STEP_PROJECT,
            title="Checking Yoke project.",
            message=f"Verifying project {local_ref.project_id} from {local_ref.source}.",
            work=lambda: existing_project_lookup.find_by_project_id(
                api_url=self.result.api_url,
                token=token,
                project_id=local_ref.project_id,
            ),
            on_success=lambda project: self._after_existing_project_lookup(
                project,
                match_source=existing_project_lookup.MATCH_SOURCE_LOCAL_CHECKOUT,
                local_source=local_ref.source,
            ),
            on_error=lambda exc: self._goto_existing_project_lookup_error(
                exc,
                retry=lambda: self._after_local_checkout_source(value),
            ),
            group="onboard-existing-project",
        )

    def _goto_project_details(self: _Shell) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        suggested_slug = steps.slug_from_checkout(self.result.project_checkout)
        branch = self.result.project_source_default_branch
        fields = project_details.fields(
            slug=suggested_slug,
            branch_from_source=branch,
        )

        def builder():
            self._begin_form(fields, on_done=self._after_project_details)
            return project_details.body(fields, branch_from_source=branch)

        self._goto(
            _View(
                STEP_PROJECT,
                builder,
                lambda _choice: self._submit_pending_form(),
            )
        )

    def _after_project_details(self: _Shell, values: dict[str, str]) -> None:
        self.result.project_slug = values["slug"]
        self.result.project_name = values["name"]
        self.result.project_default_branch = (
            self.result.project_source_default_branch
            or values.get("branch")
            or onboard_project.DEFAULT_NEW_REPO_BRANCH
        )
        self.result.project_public_item_prefix = values["prefix"].upper()
        if self.result.project_mode in PUBLISH_MODES:
            self._goto_publish_prompt()
            return
        self._after_name_clone()

    def _record_existing_project(
        self: _Shell,
        project: existing_project_lookup.ExistingProject,
        *,
        match_source: str | None = None,
        local_source: str | None = None,
    ) -> None:
        onboard_existing_project.record_match(
            self.result,
            project,
            match_source=match_source,
            local_source=local_source,
        )

    def _after_existing_project_lookup(
        self: _Shell,
        project: Any,
        *,
        match_source: str | None = None,
        local_source: str | None = None,
    ) -> None:
        if project is None:
            self._goto_project_details()
            return
        if (
            self.result.project_mode == onboard_project.PROJECT_MODE_LOCAL_CHECKOUT
            and project.github_repo
        ):
            try:
                onboard_local_checkout_identity.require_matching_origin(
                    self.result.project_checkout or "",
                    github_repo=project.github_repo,
                    web_url=onboard_wizard_github_state.clone_web_url(self.result),
                )
            except RuntimeError as exc:
                self._goto_existing_project_lookup_error(
                    exc,
                    retry=lambda: self._after_local_checkout_source(
                        self.result.project_checkout or ""
                    ),
                )
                return
        self._record_existing_project(
            project,
            match_source=match_source,
            local_source=local_source,
        )
        if (
            not self.result.project_github_repo
            and self.result.project_checkout
            and self.result.project_mode == onboard_project.PROJECT_MODE_LOCAL_CHECKOUT
        ):
            try:
                onboard_local_checkout_identity.inspect(
                    self.result,
                    self.result.project_checkout,
                )
            except RuntimeError:
                pass
        self._goto_existing_project_ready()

    def _after_existing_project_ready(self: _Shell) -> None:
        if (
            self.result.project_github_adoption == GITHUB_ADOPTION_DISABLED
            and self.result.project_github_repo
            and github_connected(self.result)
        ):
            self._after_prefix(self.result.project_public_item_prefix)
            return
        if onboard_wizard_board_art_apply.board_art_exists(
            self.result.project_checkout,
        ):
            self._goto_hosting()
            return
        self._goto_board_art()

    def _yoke_token_for_project_lookup(self: _Shell) -> str | None:
        try:
            return yoke_token_verify.read_token_source(
                token=self.result.token,
                token_file=self.result.token_file,
                source_kind=self.result.token_source_kind,
            )
        except yoke_token_verify.YokeTokenVerificationError:
            return None


__all__ = ["PUBLISH_MODES", "ProjectIdentityFlow"]
