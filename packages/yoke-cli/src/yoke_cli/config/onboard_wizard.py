"""Full-screen Textual wizard for ``yoke onboard``.

This is a presentation layer over the existing pure assembly function
:func:`yoke_cli.config.onboard.build_report`. The wizard collects the same
field set the readline prompt did, previews the write plan distinguishing
machine / Yoke-core-database / repo-local / source-dev-admin writes, and
applies on a single confirm. It never reimplements report assembly and never
prints secrets — token inputs use password fields.

``textual`` is imported lazily inside :func:`run_wizard` so non-interactive and
import-graph paths never require it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, TextIO

from yoke_cli.config import machine_config
from yoke_cli.config import onboard_destinations
from yoke_cli.config import onboard_machine_github
from yoke_cli.config import onboard_project
from yoke_cli.config.project_github_adoption import GITHUB_ADOPTION_STORE_CHOICES

# Project GitHub binding choice surfaced as a first-class wizard option.
PROJECT_GITHUB_REUSE_MACHINE = "reuse-machine"


class WizardCancelled(RuntimeError):
    """The operator quit the wizard before completing onboarding."""


class WizardApplyError(RuntimeError):
    """Apply failed after the wizard created a durable report."""

    def __init__(
        self,
        message: str,
        *,
        failed_step: str | None = None,
        report_path: str | None = None,
        resume_command: str | None = None,
    ) -> None:
        super().__init__(message)
        self.failed_step = failed_step
        self.report_path = report_path
        self.resume_command = resume_command


@dataclass
class WizardRunResult:
    """Terminal state returned by the Textual wizard."""

    exit_code: int
    cancelled: bool = False
    error: str | None = None
    failed_step: str | None = None
    report_path: str | None = None
    resume_command: str | None = None


@dataclass
class WizardResult:
    """Collected field set, one-to-one with ``build_report`` keyword args."""

    config_path: str
    env_name: str
    api_url: str
    # Deployment destination — where this Yoke lives (local machine, team
    # server, or the hosted platform). Distinct from ``mode`` (quick /
    # advanced) and stored as a non-secret input so resume restores it.
    destination: str = onboard_destinations.DEFAULT_DESTINATION
    token: str | None = None
    token_file: str | None = None
    token_source_kind: str = "prompt"
    yoke_token_verification: dict[str, Any] | None = None
    mode: str = "quick"
    apply: bool = False
    machine_github_choice: str = onboard_machine_github.CHOICE_SKIP
    machine_github_api_url: str | None = None
    machine_github_token: str | None = None
    machine_github_token_file: str | None = None
    machine_github_token_source_kind: str | None = None
    machine_github_verification: dict[str, Any] | None = None
    project_mode: str = onboard_project.PROJECT_MODE_MACHINE_ONLY
    project_remote_url: str | None = None
    project_checkout: str | None = None
    project_slug: str | None = None
    project_name: str | None = None
    project_org: str | None = None
    project_github_repo: str | None = None
    project_default_branch: str | None = None
    project_public_item_prefix: str | None = None
    existing_project_id: int | None = None
    existing_project_match_source: str | None = None
    existing_project_local_source: str | None = None
    project_github_adoption: str | None = None
    project_github_token: str | None = None
    project_github_token_file: str | None = None
    # "Also publish to GitHub?" answer. When the user publishes, the wizard
    # creates the repo at apply time under the chosen owner; the assembled
    # PublishRequest carries the inputs through build_report.
    project_publish_to_github: bool = False
    project_publish_owner: str | None = None
    project_publish_owner_login: str | None = None
    project_publish_repo_name: str | None = None
    # Visibility of the repo created for the clone "Duplicate it" outcome (and
    # the default for any created repo). Private is the safe default; the
    # make-it-mine visibility step flips it to public on request.
    project_publish_private: bool = True
    # Clone-outcome answers (clone path only). The outcome selects the post-clone
    # remote choreography; keep_upstream is honored only by "make it mine"; the
    # ClonePlan carries the make-it-mine PublishRequest and the fallback token.
    project_clone_outcome: str | None = None
    project_clone_keep_upstream: bool = True
    # Default branch detected from the clone source (via ls-remote --symref) at
    # the URL step. The clone path uses the source's real default branch instead
    # of prompting — a clone of a `master` repo records `master`, not a guessed
    # `main`. None until detected or when detection fails (then the flow falls
    # back to the plain `main` default).
    project_source_default_branch: str | None = None
    # Set when an existing-folder checkout already had a git remote and the
    # publish offer was auto-skipped. Distinguishes "keep the folder's remote"
    # from a deliberate "no GitHub" choice on the review screen.
    project_keep_existing_remote: bool = False
    # Board-art step state (collected in memory; materialized into
    # ``.yoke/board-art`` at apply, never passed to build_report). The word
    # seeds the master map and is the default for each header; the seed makes
    # reroll deterministic; the variants are the saved header pieces.
    board_art_word: str | None = None
    board_art_seed: str | None = None
    board_art_variants: list = field(default_factory=list)

    def _publish_request_from_owner(self) -> Any:
        """Assemble a PublishRequest from the chosen owner/repo, or None.

        Shared by the "Also publish to GitHub?" path and the clone "make it
        mine" path. Returns None without a chosen owner or usable GitHub
        authorization; there is nothing to create the repo with in that case.
        """
        from yoke_cli.config.onboard_project import PublishRequest

        if not (self.project_publish_owner and self.machine_github_token):
            return None
        return PublishRequest(
            owner=self.project_publish_owner,
            name=(self.project_publish_repo_name or self.project_slug or "project"),
            user_login=(self.project_publish_owner_login or ""),
            token=self.machine_github_token,
            api_url=(self.machine_github_api_url or "https://api.github.com"),
            private=self.project_publish_private,
        )

    def build_publish_request(self) -> Any:
        """Assemble the "Also publish to GitHub?" PublishRequest, or None.

        Returns None for the clone path (clones re-home through the ClonePlan,
        never the publish path) and unless the user chose to publish with
        usable GitHub authorization, so the publish is silently a no-op the
        Finish plan reflects.
        """
        if self.project_mode in onboard_project.PROJECT_REMOTE_MODES:
            return None
        if not self.project_publish_to_github:
            return None
        return self._publish_request_from_owner()

    def build_clone_plan(self) -> Any:
        """Assemble a ClonePlan from the clone-outcome answers, or None.

        Returns None for non-clone modes and when no outcome was chosen (the
        default just-clone with today's behavior). GitHub authorization for
        the private-clone fallback and the fork call is captured before project
        binding. "Make it mine" carries a PublishRequest built from the chosen
        owner/repo so the new private repo is created at apply.
        """
        from yoke_cli.config.onboard_project import ClonePlan
        from yoke_cli.config.project_clone_support import (
            CLONE_OUTCOME_MAKE_IT_MINE,
        )

        if self.project_mode not in onboard_project.PROJECT_REMOTE_MODES:
            return None
        if not self.project_clone_outcome:
            if self.existing_project_id:
                return ClonePlan(
                    fallback_token=self.machine_github_token,
                    fork_api_url=(
                        self.machine_github_api_url or "https://api.github.com"
                    ),
                )
            return None
        publish = None
        if self.project_clone_outcome == CLONE_OUTCOME_MAKE_IT_MINE:
            publish = self._publish_request_from_owner()
        return ClonePlan(
            outcome=self.project_clone_outcome,
            keep_upstream=self.project_clone_keep_upstream,
            publish=publish,
            fallback_token=self.machine_github_token,
            fork_api_url=(self.machine_github_api_url or "https://api.github.com"),
        )

    def default_branch_source(self) -> str | None:
        """Where the selected project default branch came from."""
        if self.existing_project_id:
            return onboard_project.DEFAULT_BRANCH_SOURCE_EXISTING_PROJECT
        if self.project_mode in onboard_project.PROJECT_REMOTE_MODES:
            if self.project_source_default_branch:
                return onboard_project.DEFAULT_BRANCH_SOURCE_SOURCE_REPO
            return onboard_project.DEFAULT_BRANCH_SOURCE_SOURCE_FALLBACK
        return None

    def build_report_kwargs(self, *, apply: bool, check_identity: bool) -> dict[str, Any]:
        return {
            "config_path": self.config_path,
            "env_name": self.env_name,
            "api_url": self.api_url,
            "destination": self.destination,
            "token": self.token,
            "token_file": self.token_file,
            "token_source_kind": self.token_source_kind,
            "mode": self.mode,
            "apply": apply,
            "check_identity": check_identity,
            "machine_github_choice": self.machine_github_choice,
            "machine_github_api_url": self.machine_github_api_url,
            "machine_github_token": self.machine_github_token,
            "machine_github_token_file": self.machine_github_token_file,
            "machine_github_token_source_kind": self.machine_github_token_source_kind,
            "project_mode": self.project_mode,
            "project_remote_url": self.project_remote_url,
            "project_checkout": self.project_checkout,
            "project_slug": self.project_slug,
            "project_name": self.project_name,
            "project_org": self.project_org,
            "project_github_repo": self.project_github_repo,
            "project_default_branch": self.project_default_branch,
            "project_default_branch_source": self.default_branch_source(),
            "project_public_item_prefix": self.project_public_item_prefix,
            "existing_project_id": self.existing_project_id,
            "existing_project_match_source": self.existing_project_match_source,
            "existing_project_local_source": self.existing_project_local_source,
            "project_github_adoption": self.project_github_adoption,
            "project_github_token": self.project_github_token,
            "project_github_token_file": self.project_github_token_file,
            "project_github_token_stdin_value": None,
            "project_publish": self.build_publish_request(),
            "project_clone": self.build_clone_plan(),
            "project_keep_existing_remote": self.project_keep_existing_remote,
        }


def is_interactive(stdin: TextIO, stdout: TextIO) -> bool:
    return _stream_isatty(stdin) and _stream_isatty(stdout)


def _stream_isatty(stream: TextIO) -> bool:
    isatty = getattr(stream, "isatty", None)
    return bool(isatty()) if callable(isatty) else False


@dataclass
class WizardDefaults:
    """Pre-filled values from CLI flags / environment."""

    config_path: str | None = None
    env_name: str | None = None
    api_url: str | None = None
    # Deployment destination preset from CLI flags, the destination env
    # override, or a resumed run. None shows the picker.
    destination: str | None = None
    token: str | None = None
    token_file: str | None = None
    mode: str | None = None
    project_mode: str | None = None
    project_checkout: str | None = None
    apply: bool = False
    # True when the wizard launches directly after a fresh install: the flow
    # opens on an install-summary view before the PATH check. Default skips
    # that view but still runs the PATH steps.
    post_install: bool = False


def run_wizard(
    defaults: WizardDefaults,
    *,
    apply_report: Callable[..., Any],
) -> WizardRunResult:
    """Drive the wizard to a confirmed apply (or a clean cancel).

    ``apply_report`` receives the final ``build_report`` keyword dict and is
    responsible for calling ``build_report`` and rendering its result. Returning
    a falsy value or raising is the caller's contract; the wizard only collects
    fields, previews the plan, and gates the single apply confirm.
    """
    try:
        from yoke_cli.config.onboard_wizard_app import OnboardWizardApp
    except ImportError as exc:  # textual missing from an unusual install
        raise WizardCancelled(
            "the onboarding wizard requires the 'textual' package; reinstall the "
            f"Yoke CLI or run onboarding non-interactively (--non-interactive). {exc}"
        ) from exc

    app = OnboardWizardApp(defaults=defaults, apply_report=apply_report)
    app.run()
    if app.cancelled:
        return WizardRunResult(exit_code=130, cancelled=True)
    return WizardRunResult(
        exit_code=app.exit_code,
        cancelled=False,
        error=app.last_error,
        failed_step=app.failed_step,
        report_path=app.report_path,
        resume_command=app.resume_command,
    )


def default_config_path(config_path: str | None) -> str:
    return str(machine_config.config_path(config_path))


def reuse_choice_to_adoption(choice: str) -> str:
    """Translate the wizard's reuse-machine choice to a store adoption value."""
    if choice == PROJECT_GITHUB_REUSE_MACHINE:
        return GITHUB_ADOPTION_STORE_CHOICES[0]
    return choice


__all__ = [
    "PROJECT_GITHUB_REUSE_MACHINE",
    "WizardApplyError",
    "WizardCancelled",
    "WizardDefaults",
    "WizardResult",
    "WizardRunResult",
    "default_config_path",
    "is_interactive",
    "reuse_choice_to_adoption",
    "run_wizard",
]
