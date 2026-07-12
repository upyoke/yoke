"""Consolidated pre-flight re-check for the onboarding wizard's Review screen.

The per-step validators (``onboard_input_validation``) catch bad input as it is
entered, but state can drift between a step and Apply — a folder can fill up, a
token can be revoked, the chosen repo name can be claimed on GitHub, or git can
be missing. :func:`preflight_problems` re-runs every relevant check at once on
the collected :class:`WizardResult`, so the Review screen can render ALL remaining
problems together and guard Apply until they clear, rather than failing mid-apply
with one error and a half-written checkout.

Each network/auth probe is injected so the Review render stays offline in tests;
the live wizard wires the real probes. A returned empty list means "clear to
apply"; a non-empty list is the ordered set of problems to show.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from yoke_cli.config import onboard_input_validation as validation
from yoke_cli.config import onboard_credential_replacement
from yoke_cli.config import onboard_project
from yoke_cli.config import project_git_prerequisite
from yoke_cli.config import project_clone_resume
from yoke_cli.config import onboard_wizard_github_state
from yoke_cli.config.project_clone_support import (
    CLONE_OUTCOME_FORK,
    CLONE_OUTCOME_MAKE_IT_MINE,
)
from yoke_cli.config.project_github_adoption import GITHUB_ADOPTION_APP_BINDING

REPO_FREE = "free"
REPO_EMPTY_RESUMABLE = "exists-empty-resumable"
REPO_POPULATED_BLOCKING = "exists-populated-blocking"
REPO_AMBIGUOUS_BLOCKING = "inaccessible-or-ambiguous-blocking"

_HTTP_OK = 200
_HTTP_NOT_FOUND = 404
_HTTP_EMPTY_REPOSITORY = 409


class _ResultLike(Protocol):  # pragma: no cover - structural typing only
    project_mode: str
    project_checkout: str | None
    project_remote_url: str | None
    project_github_repo: str | None
    project_publish_to_github: bool
    project_publish_owner: str | None
    project_publish_repo_name: str | None
    machine_github_api_url: str | None
    config_path: str
    env_name: str
    token: str | None
    token_file: str | None
    machine_github_choice: str | None


@dataclass(frozen=True)
class PreflightProbes:
    """Injectable network/auth probes for the pre-flight, real by default.

    ``repo_availability`` returns one of the stable ``REPO_*`` strings for the
    chosen publish target; ``token_ok`` answers "does the connected token still
    authenticate?". Both default to None so a caller can opt out of a given probe
    (e.g. no token to check); the wizard wires real callables.
    """

    repo_availability: Callable[[str, str, str, str], str] | None = None
    token_ok: Callable[[str, str], bool] | None = None


@dataclass(frozen=True)
class PreflightResult:
    """Review pre-flight outcome: blocking problems plus advisory notes.

    ``problems`` withhold Apply until they clear; ``notes`` are informational
    lines shown on the ready-to-apply screen (e.g. an existing empty repo that
    Apply will reuse rather than create).
    """

    problems: list[str]
    notes: list[str]


def preflight(
    result: _ResultLike, *, probes: PreflightProbes | None = None
) -> PreflightResult:
    """Run the Review pre-flight once, returning problems and advisory notes.

    Checks run cheap -> expensive: git presence, then the target folder's
    filesystem state, then the network probes (only when the inputs and the
    matching probe are present). A machine-only run has no project surface to
    re-check and is always clear.
    """
    probes = probes or PreflightProbes()
    problems = onboard_credential_replacement.replacement_problems_from_result(result)
    mode = getattr(result, "project_mode", None)
    if mode in (None, onboard_project.PROJECT_MODE_MACHINE_ONLY):
        return PreflightResult(problems=problems, notes=[])

    # git is required for every checkout-creating / cloning mode. Earlier TUI
    # steps fail fast, but Review keeps this as a drift/backstop check.
    if not project_git_prerequisite.git_available():
        problems.append(project_git_prerequisite.missing_git_message())

    problems.extend(_folder_problems(result, mode))
    net_problems, net_notes = _network_findings(result, probes)
    problems.extend(net_problems)
    return PreflightResult(problems=problems, notes=net_notes)


def preflight_problems(
    result: _ResultLike, *, probes: PreflightProbes | None = None
) -> list[str]:
    """Backwards-compatible accessor for just the blocking problems."""
    return preflight(result, probes=probes).problems


def _folder_problems(result: _ResultLike, mode: str) -> list[str]:
    checkout = getattr(result, "project_checkout", None)
    if not checkout:
        return []
    # A clone needs an empty/new target; create/existing-folder tolerate an
    # existing dir (it adopts) but still reject a file / unwritable parent.
    if mode in onboard_project.PROJECT_REMOTE_MODES:
        remote = str(getattr(result, "project_remote_url", None) or "")
        if remote and project_clone_resume.existing_clone_matches(
            Path(str(checkout)).expanduser(),
            remote,
            web_url=onboard_wizard_github_state.clone_web_url(result),
        ):
            error = validation.validate_clone_resume_target_folder(str(checkout))
        else:
            error = validation.validate_clone_target_folder(str(checkout))
    else:
        error = validation.validate_create_target_folder(str(checkout))
    return [error] if error else []


def _network_findings(
    result: _ResultLike, probes: PreflightProbes
) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    notes: list[str] = []
    needs_github_token = bool(
        getattr(result, "project_publish_to_github", False)
        or getattr(result, "project_clone_outcome", None)
        in (CLONE_OUTCOME_FORK, CLONE_OUTCOME_MAKE_IT_MINE)
        or getattr(result, "project_github_adoption", None)
        == GITHUB_ADOPTION_APP_BINDING
    )
    if not needs_github_token:
        return problems, notes
    # Review is a dry-run surface. Refreshing the App token here would rotate
    # the persisted refresh credential before Apply, so all live App and repo
    # checks run only after the operator confirms Apply.
    notes.append("Live GitHub access will be checked during Apply.")
    return problems, notes


def _slug_fallback(result: _ResultLike) -> str | None:
    repo = getattr(result, "project_github_repo", None)
    if repo and "/" in repo:
        return repo.split("/", 1)[1]
    return None


def default_probes() -> PreflightProbes:
    """Build the live probes the wizard wires for the Review pre-flight.

    ``token_ok`` refreshes the App user's live installation snapshot;
    ``repo_availability`` probes
    the target repo and, when it exists, its commits endpoint. Unknown transport
    states block Review as ambiguous instead of being treated as free.
    """
    from yoke_cli.config import github_app_user_api
    from yoke_cli.config import github_publish_transport

    def _token_ok(api_url: str, token: str) -> bool:
        try:
            github_app_user_api.discover_access(
                api_url=api_url, access_token=token,
            )
            return True
        except github_app_user_api.GitHubAppUserApiError:
            return False

    def _repo_availability(api_url: str, token: str, owner: str, name: str) -> str:
        try:
            github_publish_transport.request_json(
                api_url, f"/repos/{owner}/{name}", token,
            )
        except github_publish_transport.GitHubPublishError as exc:
            return REPO_FREE if exc.status == _HTTP_NOT_FOUND else REPO_AMBIGUOUS_BLOCKING
        try:
            github_publish_transport.request_json(
                api_url, f"/repos/{owner}/{name}/commits", token,
            )
        except github_publish_transport.GitHubPublishError as exc:
            if exc.status == _HTTP_EMPTY_REPOSITORY:
                return REPO_EMPTY_RESUMABLE
            return REPO_AMBIGUOUS_BLOCKING
        return REPO_POPULATED_BLOCKING

    return PreflightProbes(repo_availability=_repo_availability, token_ok=_token_ok)


__all__ = [
    "PreflightProbes",
    "PreflightResult",
    "REPO_AMBIGUOUS_BLOCKING",
    "REPO_EMPTY_RESUMABLE",
    "REPO_FREE",
    "REPO_POPULATED_BLOCKING",
    "default_probes",
    "preflight",
    "preflight_problems",
]
