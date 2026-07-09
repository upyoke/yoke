"""Clone-path step transitions for the ``yoke onboard`` wizard.

A mixin composed alongside :class:`onboard_wizard_flow.WizardFlow` into
:class:`onboard_wizard_app.OnboardWizardApp`. It owns the clone path's screens
    after the clone folder: the public/private visibility split (public pastes a
    URL, private picks from connected GitHub repos), the 3-way post-URL outcome
    (clone / make-it-mine / fork), and the make-it-mine new-repo visibility step.
Each answer is recorded onto ``self.result`` and routed back into the shared
project step (``_goto_slug``) or, for make-it-mine, on through the reused publish
owner-picker. Make-it-mine always keeps the source as a pull-only ``upstream``
remote, so a private copy can still pull from a public original. It holds no
report-assembly logic; the ClonePlan it populates is assembled in
:class:`onboard_wizard.WizardResult`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Protocol

from yoke_cli.config import github_publish
from yoke_cli.config import github_token_capability
from yoke_cli.config import onboard_input_validation as input_validation
from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config import onboard_wizard_project_screens as project_screens
from yoke_cli.config import project_clone_support as clone_support
from yoke_cli.config.onboard_wizard_flow_clone_source import CloneSourceFlow
from yoke_cli.config.onboard_wizard_widgets import STEP_PROJECT


def fetch_private_repos(api_url: str, token: str) -> list:
    """Private-repo seam for the clone picker — patched in tests so none hit GitHub."""
    return github_publish.list_user_repos(api_url, token, private_only=True)


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
    def _goto_slug(self) -> None: ...
    def _goto_owner_picker(self) -> None: ...
    def _after_repo(self, value: str) -> None: ...
    def _goto_project_mode(self) -> None: ...
    def _run_checking(self, **kwargs) -> None: ...
    def _goto_existing_project_ready(self) -> None: ...


class CloneFlow(CloneSourceFlow):
    # ── Clone visibility (public / private split) ───────────

    def _goto_clone_visibility(self: _Shell) -> None:
        # Listing private repos needs connected GitHub authorization. Without it,
        # the private branch can't enumerate anything, so the visibility screen
        # is omitted entirely and the clone path stays on the original paste-URL
        # input rather than offering a row that dead-ends.
        if not self.result.machine_github_token:
            self._goto_clone_url_input()
            return
        self._goto(self._selection_view(
            STEP_PROJECT,
            "Is the repo public or private?",
            "Public repos clone from a URL; private ones come from your GitHub account.",
            project_screens.CLONE_VISIBILITY_ROWS, self._on_clone_visibility,
        ))

    def _on_clone_visibility(self: _Shell, choice: str) -> None:
        if choice == project_screens.CLONE_VISIBILITY_PRIVATE:
            self._goto_private_repo_picker()
            return
        self._goto_clone_url_input()

    def _goto_clone_url_input(self: _Shell) -> None:
        self._goto_input(
            STEP_PROJECT, "Clone a project from GitHub.",
            "Paste the repo's git URL — Yoke clones it into a new folder.",
            placeholder="https://github.com/acme/project.git",
            on_done=self._after_remote,
            allow_placeholder=False,
        )

    def _goto_private_repo_picker(self: _Shell) -> None:
        self._run_checking(
            step=STEP_PROJECT,
            title="Checking private repos.",
            message="Loading repos available through GitHub authorization.",
            work=self._fetch_private_repos,
            on_success=self._show_private_repo_picker,
            on_error=self._goto_private_repo_picker_error,
            group="onboard-private-repos",
        )

    def _fetch_private_repos(self: _Shell) -> list:
        return fetch_private_repos(
            self.result.machine_github_api_url or "https://api.github.com",
            self.result.machine_github_token or "",
        )

    def _show_private_repo_picker(self: _Shell, repos: Any) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        if not repos:
            # No private repos are reachable: the picker would be an empty
            # SelectionList whose Enter no-ops (action_choose guards on its rows),
            # and the screen has no input — a dead-end. Fall back to pasting the
            # URL, mirroring the no-authorization and public branches.
            self._goto_clone_url_input()
            return
        self._goto(_View(
            STEP_PROJECT,
            lambda: project_screens.repo_picker_body(repos),
            self._after_remote,
        ))

    def _goto_private_repo_picker_error(self: _Shell, exc: BaseException) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        self._goto(_View(
            STEP_PROJECT,
            lambda: steps.verification_body(
                "Couldn't load private repos.",
                str(exc),
                ["Check the token, GitHub availability, and network connection."],
                steps.PROBE_RETRY_ROWS,
                ok=False,
            ),
            self._on_private_repo_picker_error,
        ))

    def _on_private_repo_picker_error(self: _Shell, choice: str) -> None:
        if choice == "retry":
            self._goto_private_repo_picker()
            return
        self._goto_clone_url_input()

    # ── Local folder (defaults from the repo name) ──────────

    def _goto_clone_folder(self: _Shell) -> None:
        repo = project_screens.default_repo(self.result.project_remote_url)
        slug = repo.rsplit("/", 1)[-1] if repo else "my-project"
        self._goto_input(
            STEP_PROJECT, "Where should Yoke clone it?",
            "Yoke clones the repo into this new folder. Press Enter to accept "
            "the default.",
            placeholder=f"~/code/{slug}",
            on_done=self._after_clone_folder,
            validate=self._validate_clone_folder,
        )

    def _validate_clone_folder(self: _Shell, value: str) -> Optional[str]:
        """Validate the clone folder, allowing a matching prior partial clone.

        Generic empty/new + writable-parent validation, except a folder that is
        already a clone of THIS source is accepted — the resumable-apply path
        (and the Resume / Start-over screen) handles it rather than the inline
        "already has files" rejection a foreign non-empty folder gets.
        """
        target = Path(value).expanduser()
        remote = self.result.project_remote_url
        if remote and clone_support.existing_clone_matches(target, remote):
            return None
        return input_validation.validate_clone_target_folder(value)

    def _after_clone_folder(self: _Shell, value: str) -> None:
        # Empty input adopts the ~/code/<repo> placeholder (allow_placeholder).
        self.result.project_checkout = value
        # A target that already holds a matching clone of this source is a prior
        # partial run — offer Resume vs Start over instead of silently re-cloning.
        remote = self.result.project_remote_url
        target = Path(value).expanduser()
        if remote and clone_support.existing_clone_matches(target, remote):
            self._goto_resume_or_start_over(value)
            return
        if self.result.existing_project_id:
            self._goto_existing_project_ready()
            return
        self._goto_clone_outcome()

    def _goto_resume_or_start_over(self: _Shell, checkout: str) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        self._goto(_View(
            STEP_PROJECT,
            lambda: project_screens.resume_or_start_over_body(checkout),
            self._on_resume_or_start_over,
        ))

    def _on_resume_or_start_over(self: _Shell, choice: str) -> None:
        if choice == "start-over":
            self._start_over_checkout()
        # Resume (and the post-removal start-over) both continue into the normal
        # outcome flow; the resumable apply steps skip whatever already landed.
        if self.result.existing_project_id:
            self._goto_existing_project_ready()
            return
        self._goto_clone_outcome()

    def _start_over_checkout(self: _Shell) -> None:
        """Remove the partial checkout so the apply starts from a clean slate.

        Only ever runs against a folder the user just confirmed is a prior clone
        of the chosen source — never an arbitrary path — so the removal is scoped
        to Yoke's own partial output.
        """
        import shutil

        target = Path(self.result.project_checkout or "").expanduser()
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)

    # ── Clone outcome (clone path only) ─────────────────────

    def _source_push_access(self: _Shell) -> Optional[bool]:
        """Probe whether GitHub authorization can push to the source repo.

        Runs the non-mutating write probe (``can_write_repo``) against the
        cloned source's ``owner/repo``. Returns True when authorization can push
        to it (writable variant), False or None otherwise (read-only variant —
        the safe default, since "Clone it" has no side effects when in doubt).
        Returns None without connected GitHub authorization or a recognizable
        source repo: there is nothing to probe, so the read-only variant shows.
        Single seam so tests patch one method.
        """
        token = self.result.machine_github_token
        source_repo = project_screens.default_repo(self.result.project_remote_url)
        if not (token and source_repo):
            return None
        api_url = self.result.machine_github_api_url or "https://api.github.com"
        return github_token_capability.can_write_repo(api_url, token, source_repo)

    def _goto_clone_outcome(self: _Shell) -> None:
        source_repo = project_screens.default_repo(self.result.project_remote_url)
        if self.result.machine_github_token and source_repo:
            self._run_checking(
                step=STEP_PROJECT,
                title="Checking source access.",
                message="Seeing whether GitHub authorization can push to the source repo.",
                work=self._source_push_access,
                on_success=self._show_clone_outcome,
                on_error=lambda _exc: self._show_clone_outcome(None),
                group="onboard-source-access",
            )
            return
        self._show_clone_outcome(None)

    def _show_clone_outcome(self: _Shell, push_access: Any) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        remote = self.result.project_remote_url
        has_token = bool(self.result.machine_github_token)
        self._goto(_View(
            STEP_PROJECT,
            lambda: project_screens.clone_outcome_body(
                remote, has_token=has_token, push_access=push_access,
            ),
            self._on_clone_outcome,
        ))

    def _on_clone_outcome(self: _Shell, choice: str) -> None:
        self.result.project_clone_outcome = choice
        if choice == clone_support.CLONE_OUTCOME_MAKE_IT_MINE:
            self._goto_new_repo_visibility()
            return
        self._goto_slug()

    def _goto_new_repo_visibility(self: _Shell) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        self._goto(_View(
            STEP_PROJECT,
            project_screens.new_repo_visibility_body,
            self._on_new_repo_visibility,
        ))

    def _on_new_repo_visibility(self: _Shell, choice: str) -> None:
        # "Duplicate it" always keeps the source as a pull-only ``upstream``
        # remote (``project_clone_keep_upstream`` stays at its True default), so
        # the new repo can pull from the original even when it has a different
        # visibility — a private copy of a public original. Route straight to the
        # name + owner-picker path the publish/fork outcomes use.
        self.result.project_publish_private = (
            choice == project_screens.NEW_REPO_PRIVATE
        )
        self._goto_slug()

    def _after_name_clone(self: _Shell) -> None:
        """Route the clone path after the project name is entered.

        Make-it-mine reuses the publish owner-picker + repo-name screens so the
        new private repo's target is chosen the same way as a fresh publish (the
        re-home itself runs through the ClonePlan at apply). Without a connected
        token there is nothing to create the repo with, so the wizard degrades
        to a plain clone rather than stranding the user. Just-clone and fork
        record the source repo as the metadata default.
        """
        if (
            self.result.project_clone_outcome
            == clone_support.CLONE_OUTCOME_MAKE_IT_MINE
        ):
            if not self.result.machine_github_token:
                self.result.project_clone_outcome = (
                    clone_support.CLONE_OUTCOME_JUST_CLONE
                )
                self._after_repo("")
                return
            self.result.project_publish_to_github = True
            self._goto_owner_picker()
            return
        self._after_repo(project_screens.default_repo(self.result.project_remote_url) or "")


__all__ = ["CloneFlow", "fetch_private_repos"]
