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
from typing import TYPE_CHECKING, Any, Callable, Protocol

from yoke_cli.config import existing_project_lookup
from yoke_cli.config import github_publish
from yoke_cli.config import machine_config
from yoke_cli.config import onboard_github_copy
from yoke_cli.config import onboard_input_validation as input_validation
from yoke_cli.config import onboard_project
from yoke_cli.config import onboard_wizard_board_art
from yoke_cli.config import yoke_token_verify
from yoke_cli.config.onboard_error_friendly import friendly_permission_error

from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config.onboard_wizard import (
    PROJECT_GITHUB_REUSE_MACHINE,
    reuse_choice_to_adoption,
)
from yoke_cli.config.onboard_wizard_widgets import (
    STEP_FINISH,
    STEP_PROJECT,
    SelectionRow,
)
from yoke_cli.config.project_publish_support import is_existing_project_dir
from yoke_cli.project_install import source_dev

# Modes that offer the "Also publish to GitHub?" follow-up. A clone always
# brings its own remote and source-dev/admin develops Yoke itself, so neither
# publishes.
PUBLISH_MODES = (
    onboard_project.PROJECT_MODE_CREATE_REPO,
    onboard_project.PROJECT_MODE_LOCAL_CHECKOUT,
)


def _is_yoke_source_checkout(path: Path) -> bool:
    try:
        return source_dev.is_yoke_source_checkout(path.expanduser())
    except OSError:
        return False


def _existing_project_match_summary(result: Any) -> str:
    source = getattr(result, "existing_project_match_source", None)
    if source == existing_project_lookup.MATCH_SOURCE_LOCAL_CHECKOUT:
        return "Local project metadata matched a Yoke core database project."
    if source == existing_project_lookup.MATCH_SOURCE_GITHUB_REPO:
        return "The Yoke core database already has a project for this GitHub repo."
    return "Yoke found an existing project and will reuse it."


def _existing_project_match_lines(result: Any) -> list[str]:
    source = getattr(result, "existing_project_match_source", None)
    project_id = getattr(result, "existing_project_id", None)
    github_repo = str(getattr(result, "project_github_repo", "") or "").strip()
    local_source = str(getattr(result, "existing_project_local_source", "") or "").strip()

    if source == existing_project_lookup.MATCH_SOURCE_LOCAL_CHECKOUT:
        local_label = local_source or "local checkout metadata"
        return [
            f"Local machine: found project id {project_id} in {local_label}.",
            f"Yoke core database: verified project id {project_id}.",
        ]
    if source == existing_project_lookup.MATCH_SOURCE_GITHUB_REPO:
        repo_label = f"GitHub repo {github_repo}" if github_repo else "the GitHub repo"
        return [
            f"Yoke core database: matched {repo_label}.",
            "Local machine: no existing Yoke project metadata was used.",
        ]
    return ["Yoke core database: existing project verified."]


def fetch_repo_owners(api_url: str, token: str) -> list:
    """Owner-list seam for the picker — patched in tests so none hit GitHub."""
    return github_publish.list_repo_owners(api_url, token)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.onboard_wizard_app import _View


class _Shell(Protocol):  # pragma: no cover - structural typing only
    result: Any
    _pending_stored_project_checkout: str | None
    _preset_dev_checkout: str | None
    _project_mode_preset: bool
    _project_preset_attempted: bool
    _stored_project_attempted: bool
    _stored_project_checkouts: list[machine_config.ConfiguredProject]

    def _goto(self, view: "_View") -> None: ...
    def _selection_view(self, step, title, subtitle, rows, on_select) -> "_View": ...
    def _goto_input(self, step, title, subtitle, *, placeholder, on_done,
                    password: bool = False,
                    allow_placeholder: bool = True,
                    validate=None,
                    initial_value: str = "") -> None: ...
    def _start_dev_flow(self) -> None: ...
    def _check_project_git(self, mode: str) -> None: ...
    def _run_checking(self, **kwargs) -> None: ...
    def _goto_finish(self) -> None: ...
    def _goto_board_art_intro(self) -> None: ...


class WizardFlow:
    # ── Project step ────────────────────────────────────────

    def _goto_project_mode(self: _Shell) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        if self._project_mode_preset and not self._project_preset_attempted:
            self._project_preset_attempted = True
            self._on_project_mode(self.result.project_mode)
            return
        if self._stored_project_checkouts and not self._stored_project_attempted:
            self._stored_project_attempted = True
            self._goto_stored_project_picker()
            return
        self._goto(_View(STEP_PROJECT, steps.project_mode_body, self._on_project_mode))

    def _goto_stored_project_picker(self: _Shell) -> None:
        rows: list[SelectionRow] = []
        for index, project in enumerate(self._stored_project_checkouts):
            checkout = str(project.checkout)
            rows.append(SelectionRow(
                f"stored:{index}",
                checkout,
                f"project id {project.project_id}",
            ))
            if _is_yoke_source_checkout(project.checkout):
                rows.append(SelectionRow(
                    f"source-dev:{index}",
                    "Develop Yoke itself",
                    f"use {checkout} as the source checkout",
                ))
        rows.append(SelectionRow(
            "other",
            "Choose another project",
            "show all project options",
        ))
        rows.append(SelectionRow(
            "none",
            "Don't set up a project now",
            "just the machine",
        ))
        self._goto(self._selection_view(
            STEP_PROJECT,
            "Use an existing project mapping?",
            "Yoke found project mappings saved on this machine. Reuse one, or choose another path.",
            rows,
            self._on_stored_project_choice,
        ))

    def _on_stored_project_choice(self: _Shell, choice: str) -> None:
        if choice == "other":
            self._goto_project_mode()
            return
        if choice == "none":
            self._on_project_mode(onboard_project.PROJECT_MODE_MACHINE_ONLY)
            return
        if choice.startswith("source-dev:"):
            try:
                index = int(choice.split(":", 1)[1])
                project = self._stored_project_checkouts[index]
            except (IndexError, TypeError, ValueError):
                self._goto_project_mode()
                return
            self._preset_dev_checkout = str(project.checkout)
            self.result.project_checkout = str(project.checkout)
            self._on_project_mode(onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN)
            return
        if choice.startswith("stored:"):
            try:
                index = int(choice.split(":", 1)[1])
                project = self._stored_project_checkouts[index]
            except (IndexError, TypeError, ValueError):
                self._goto_project_mode()
                return
            self._use_stored_project_checkout(project)
            return
        self._goto_project_mode()

    def _use_stored_project_checkout(
        self: _Shell,
        project: machine_config.ConfiguredProject,
    ) -> None:
        checkout = str(project.checkout)
        self.result.project_mode = onboard_project.PROJECT_MODE_LOCAL_CHECKOUT
        self.result.project_checkout = checkout
        self._pending_stored_project_checkout = checkout
        self._check_project_git(onboard_project.PROJECT_MODE_LOCAL_CHECKOUT)

    def _on_project_mode(self: _Shell, mode: str) -> None:
        self.result.project_mode = mode
        if mode == onboard_project.PROJECT_MODE_MACHINE_ONLY:
            steps.reset_project_fields(self.result)
            self._goto_finish()
            return
        self._check_project_git(mode)

    def _after_project_git_ready(self: _Shell, mode: str) -> None:
        if mode == onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN:
            # Develop Yoke itself: verify both grants, then find or clone the
            # Yoke checkout. The DevFlow mixin owns the whole sequence.
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
            title, subtitle = "Name your new project folder.", "Where should Yoke create it? It makes the folder and a git repo."
        else:
            title, subtitle = "Point at your project folder.", "Where's the code on this machine? Yoke makes it a git repo if it isn't."
        # Validate inline: a plain file or an unwritable parent is rejected here,
        # not at Apply. An existing non-empty dir is fine — create-new redirects
        # it to adopt-the-existing-folder in _after_checkout.
        self._goto_input(
            STEP_PROJECT, title, subtitle,
            placeholder="~/code/my-project", on_done=self._after_checkout,
            validate=input_validation.validate_create_target_folder,
        )

    def _after_checkout(self: _Shell, value: str) -> None:
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

        self._goto(_View(
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
        ))

    def _after_local_checkout_source(self: _Shell, value: str) -> None:
        from yoke_cli.config import project_clone_resume

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
        token = self._yoke_token_for_project_lookup()
        if local_ref is not None:
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
                message=(
                    f"Verifying project {local_ref.project_id} from "
                    f"{local_ref.source}."
                ),
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
            return
        remote = project_clone_resume.remote_url(Path(value).expanduser(), "origin")
        if not remote:
            self._goto_slug()
            return
        self.result.project_github_repo = (
            existing_project_lookup.normalize_github_repo(remote) or None
        )
        if not token:
            self._goto_slug()
            return
        self._run_checking(
            step=STEP_PROJECT,
            title="Checking Yoke project.",
            message="Looking for an existing project for this repo.",
            work=lambda: existing_project_lookup.find_by_github_repo(
                api_url=self.result.api_url,
                token=token,
                github_repo=remote,
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

    def _goto_slug(self: _Shell) -> None:
        suggested_slug = steps.slug_from_checkout(self.result.project_checkout)
        self._goto_input(
            STEP_PROJECT, "Name your project.",
            "Short ID — lowercase and hyphens (e.g. my-project).",
            placeholder=suggested_slug,
            initial_value=suggested_slug,
            allow_placeholder=False,
            on_done=self._after_slug,
            validate=input_validation.validate_slug,
        )

    def _after_slug(self: _Shell, value: str) -> None:
        self.result.project_slug = value
        self._goto_input(
            STEP_PROJECT, "Give it a friendly name.",
            "The display name people read — anything you like.",
            placeholder=value,
            initial_value=value,
            allow_placeholder=False,
            validate=input_validation.validate_display_name,
            on_done=self._after_name,
        )

    def _after_name(self: _Shell, value: str) -> None:
        self.result.project_name = value
        if self.result.project_mode in PUBLISH_MODES:
            self._goto_publish_prompt()  # PublishFlow mixin: publish offer
            return
        self._after_name_clone()  # CloneFlow mixin: clone-path routing

    def _record_existing_project(
        self: _Shell,
        project: existing_project_lookup.ExistingProject,
        *,
        match_source: str | None = None,
        local_source: str | None = None,
    ) -> None:
        self.result.existing_project_id = project.id
        self.result.existing_project_match_source = match_source
        self.result.existing_project_local_source = local_source
        self.result.project_slug = project.slug
        self.result.project_name = project.name
        self.result.project_github_repo = project.github_repo
        self.result.project_default_branch = project.default_branch
        self.result.project_public_item_prefix = project.public_item_prefix
        self.result.project_github_adoption = "skip"
        self.result.project_github_token = None
        self.result.project_publish_to_github = False
        self.result.project_publish_owner = None
        self.result.project_publish_repo_name = None
        self.result.board_art_word = None
        self.result.board_art_seed = None
        self.result.board_art_variants = []

    def _after_existing_project_lookup(
        self: _Shell,
        project: Any,
        *,
        match_source: str | None = None,
        local_source: str | None = None,
    ) -> None:
        if project is None:
            self._goto_slug()
            return
        self._record_existing_project(
            project,
            match_source=match_source,
            local_source=local_source,
        )
        self._goto_existing_project_ready()

    def _goto_existing_project_ready(self: _Shell) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        details = _existing_project_match_lines(self.result) + [
            f"Project id: {self.result.existing_project_id}",
            f"Project: {self.result.project_slug}",
        ]
        if self.result.project_checkout:
            checkout_label = (
                "Clone target"
                if self.result.project_mode in onboard_project.PROJECT_REMOTE_MODES
                else "Checkout"
            )
            details.insert(0, f"{checkout_label}: {self.result.project_checkout}")
        repo = self.result.project_github_repo
        if repo:
            details.append(f"GitHub repo: {repo}")
        prefix = self.result.project_public_item_prefix
        if prefix:
            details.append(f"Issue prefix: {prefix}")
        branch = self.result.project_default_branch
        if branch:
            details.append(f"Default branch: {branch}")
        self._goto(_View(
            STEP_PROJECT,
            lambda: steps.verification_body(
                "Existing Yoke project found.",
                _existing_project_match_summary(self.result),
                details,
                steps.VERIFY_OK_ROWS,
                ok=True,
            ),
            lambda _choice: self._after_existing_project_ready(),
        ))

    def _after_existing_project_ready(self: _Shell) -> None:
        if onboard_wizard_board_art.board_art_exists(self.result.project_checkout):
            self._goto_finish()
            return
        self._goto_board_art_intro()

    def _goto_existing_project_lookup_error(
        self: _Shell,
        exc: BaseException,
        *,
        retry: Callable[[], None],
    ) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        rows = [
            SelectionRow("retry", "Try again", "rerun the project check"),
            SelectionRow("back", "Back", "choose a different project option"),
        ]
        self._goto(_View(
            STEP_PROJECT,
            lambda: steps.verification_body(
                "Can't use that Yoke project.",
                str(exc),
                [
                    "Use a Yoke API token that can access this project, or choose "
                    "a different project option.",
                ],
                rows,
                ok=False,
            ),
            lambda choice: retry() if choice == "retry" else self._goto_project_mode(),
        ))

    def _yoke_token_for_project_lookup(self: _Shell) -> str | None:
        try:
            return yoke_token_verify.read_token_source(
                token=self.result.token,
                token_file=self.result.token_file,
                source_kind=self.result.token_source_kind,
            )
        except yoke_token_verify.YokeTokenVerificationError:
            return None

    # ── Branch / prefix / project-GitHub auth (shared tail) ─────────────────

    def _after_branch(self: _Shell, value: str) -> None:
        self.result.project_default_branch = value
        self._goto_input(
            STEP_PROJECT, "Pick the issue ID prefix.",
            "The PROJ in PROJ-123 — Yoke suggests one from your project name.",
            placeholder=steps.prefix_from_slug(self.result.project_slug),
            on_done=self._after_prefix,
            validate=input_validation.validate_prefix,
        )

    def _after_prefix(self: _Shell, value: str) -> None:
        self.result.project_public_item_prefix = value
        if not self.result.project_github_repo:
            self._goto_board_art_intro()
            return
        # The connected-repo row only makes sense once the machine has a GitHub
        # App authorization. Without one, drop it so the picker never offers a
        # route that cannot bind a repository.
        if self.result.machine_github_token:
            rows = steps.PROJECT_GITHUB_ROWS
        else:
            rows = steps.PROJECT_GITHUB_ROWS_NO_MACHINE
        self._goto(self._selection_view(
            STEP_PROJECT,
            onboard_github_copy.PROJECT_GITHUB_PROMPT_TITLE,
            onboard_github_copy.PROJECT_GITHUB_PROMPT_SUBTITLE,
            rows, self._on_project_github,
        ))

    def _on_project_github(self: _Shell, choice: str) -> None:
        if choice == PROJECT_GITHUB_REUSE_MACHINE and not self.result.machine_github_token:
            choice = "skip"
        if choice in (PROJECT_GITHUB_REUSE_MACHINE, "store-token"):
            self._goto_project_github_unavailable()
            return
        self.result.project_github_adoption = reuse_choice_to_adoption(choice)
        if choice == "skip":
            self.result.project_github_token = None
            self._goto_board_art_intro()
            return

    def _goto_project_github_unavailable(self: _Shell) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        self._goto(_View(
            STEP_PROJECT,
            lambda: steps.verification_body(
                "GitHub repo binding is not available here yet.",
                onboard_github_copy.PROJECT_TOKEN_PASTE_SUBTITLE,
                [
                    "The project will stay backlog-only if you continue.",
                    "Repo binding arrives through the GitHub App setup flow.",
                ],
                steps.GITHUB_APP_UNAVAILABLE_ROWS,
                ok=False,
            ),
            self._on_project_github_unavailable,
        ))

    def _on_project_github_unavailable(self: _Shell, choice: str) -> None:
        if choice == "backlog":
            self.result.project_github_adoption = "skip"
            self.result.project_github_token = None
            self._goto_board_art_intro()
            return
        self._after_prefix(self.result.project_public_item_prefix or "")

    def _after_project_token(self: _Shell, value: str) -> None:
        self.result.project_github_token = value
        self._goto_board_art_intro()

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

    def _build_finish(self) -> list:
        return steps.finish_body(
            self._review_plan,
            problems=getattr(self, "_review_problems", []),
            notes=getattr(self, "_review_notes", []),
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
        self._review_problems = list(getattr(checks, "problems", []) or [])
        self._review_notes = list(getattr(checks, "notes", []) or [])
        self._goto(_View(STEP_FINISH, self._build_finish, self._on_confirm))

    def _goto_finish_error(self: _Shell, exc: BaseException) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        self._goto(_View(
            STEP_FINISH,
            lambda: steps.error_body(str(exc)),
        ))

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
