"""The machine GitHub binding a local merge has to authorize through.

`yoke merge item` runs its engine in a child process that binds the machine's
GitHub App user authorization for the whole merge: it pins the connection the
machine profile is proven against, then reads a user token through it. A
diagnostic that answers "is GitHub healthy on this machine" has to pin the
same connection and read through the same surface, or it can report green
over a merge path that cannot authorize. Both surfaces resolve their
connection here and describe a failed read with the same verdicts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from yoke_cli.config import github_app_public_profile
from yoke_cli.config import machine_config
from yoke_contracts.github_auth_transience import GITHUB_AUTH_RETRY_RECIPE
from yoke_contracts.github_origin import (
    GitHubApiEndpoint,
    GitHubApiOriginError,
    validate_github_api_endpoint,
)


# The two bindings a merge has to prove. The stored access token is reported
# beside them but never gates readiness: a machine with no token cached yet is
# perfectly able to mint one on its next command.
READINESS_BINDINGS = ("user_authorization", "app_installation")

VERDICT_OK = "ok"
VERDICT_BROKEN = "broken"
VERDICT_BUSY = "busy"
VERDICT_UNPROVEN = "unproven"

RECONNECT_RECOVERY = (
    "machine GitHub App user authorization is unavailable for the active "
    "Yoke connection; run `yoke github status`, then reconnect GitHub with "
    "`yoke github connect`"
)
RETRY_RECOVERY = (
    "machine GitHub App user authorization could not be read right now "
    "(another local operation holds it, or GitHub could not be reached); the "
    f"stored authorization still stands, so {GITHUB_AUTH_RETRY_RECIPE}"
)
_UNCHECKED_RECOVERY = (
    "Run `yoke github status` without `--offline` to prove the merge path."
)
_TOKEN_BUSY_CODE = "github_user_token_read_busy"


@dataclass(frozen=True)
class MergePathSelection:
    """The Yoke connection a merge proves its machine App profile against."""

    endpoint: GitHubApiEndpoint
    service_api_url: str | None
    local_connection_selected: bool
    resolved: bool


def resolve_selection(
    config_path: Any | None = None,
) -> MergePathSelection:
    """Pin the machine API origin and the selected local or HTTPS Yoke service.

    Resolution never raises: the merge child binds this before it knows
    whether the run touches GitHub at all, so an unresolved selection stays a
    fail-closed fact its caller reports rather than a bind-time crash.
    """

    try:
        github = machine_config.github_config(config_path)
        endpoint = validate_github_api_endpoint(
            str(github.get("api_url") or "") if github else None
        )
        resolved = bool(github)
    except (GitHubApiOriginError, machine_config.MachineConfigError):
        return MergePathSelection(
            endpoint=validate_github_api_endpoint(None),
            service_api_url=None,
            local_connection_selected=False,
            resolved=False,
        )

    try:
        service_api_url = github_app_public_profile.selected_https_service_api_url(
            config_path
        )
    except github_app_public_profile.GitHubAppPublicProfileError:
        return MergePathSelection(
            endpoint=endpoint,
            service_api_url=None,
            local_connection_selected=False,
            resolved=False,
        )
    return MergePathSelection(
        endpoint=endpoint,
        service_api_url=service_api_url,
        local_connection_selected=service_api_url is None,
        resolved=resolved,
    )


def status_connection_scope(config_path: Any | None = None) -> dict[str, Any]:
    """Pin a status check to the connection a local merge authorizes against.

    An unresolved selection returns no scope so the status check surfaces the
    precise machine-config failure instead of a selection this cannot pin.
    """

    selection = resolve_selection(config_path)
    if not selection.resolved:
        return {}
    return {
        "service_api_url": selection.service_api_url,
        "local_connection_selected": selection.local_connection_selected,
    }


def user_authorization_binding(
    *,
    checked: bool,
    token_issue: Mapping[str, str] | None,
    authorization_revoked: bool,
) -> dict[str, str]:
    """Describe whether a merge could mint a user token on this machine."""

    if not checked:
        return _binding(
            VERDICT_UNPROVEN,
            "the merge-path GitHub authorization was not checked",
            _UNCHECKED_RECOVERY,
        )
    if token_issue:
        busy = str(token_issue.get("code") or "") == _TOKEN_BUSY_CODE
        return _binding(
            VERDICT_BUSY if busy else VERDICT_BROKEN,
            str(token_issue.get("message") or ""),
            RETRY_RECOVERY if busy else RECONNECT_RECOVERY,
        )
    if authorization_revoked:
        return _binding(
            VERDICT_BROKEN,
            "GitHub rejected the machine App user authorization",
            RECONNECT_RECOVERY,
        )
    return _binding(
        VERDICT_OK,
        "the machine can authorize a merge against the selected Yoke connection",
        "",
    )


def git_access_token_binding(
    *,
    expires_at: str | None,
    stale: bool,
) -> dict[str, str]:
    """Describe the stored access token a git command would actually carry.

    The refresh credential can be perfectly healthy while pushes fail, because
    the two are different secrets with different lifetimes. Reading this one
    costs no network call and rotates nothing, so a diagnostic can answer
    "what will the next push present?" without breaking a push in flight.
    """

    if expires_at is None:
        return _binding(
            VERDICT_UNPROVEN,
            "no access token is stored yet; the next git command mints one",
            "",
        )
    if stale:
        return _binding(
            VERDICT_UNPROVEN,
            f"the stored access token expires at {expires_at} and the next "
            "git command renews it",
            "",
        )
    return _binding(
        VERDICT_OK,
        f"a stored access token valid until {expires_at} serves git commands "
        "without renewing the authorization",
        "",
    )


def app_installation_binding(
    *,
    checked: bool,
    live_access_ok: bool,
    installation_count: int,
    permissions_usable: bool | None,
) -> dict[str, str]:
    """Describe whether the App still grants the repository access a merge needs."""

    if not checked:
        return _binding(
            VERDICT_UNPROVEN,
            "App installation access was not checked",
            _UNCHECKED_RECOVERY,
        )
    if not live_access_ok:
        return _binding(
            VERDICT_UNPROVEN,
            "App installation access could not be read from GitHub",
            "Retry `yoke github status` once GitHub is reachable.",
        )
    if not installation_count:
        return _binding(
            VERDICT_BROKEN,
            "the GitHub App has no installation access",
            "Install the App, choose repositories, then rerun `yoke github status`.",
        )
    if permissions_usable is not True:
        return _binding(
            VERDICT_BROKEN,
            "no App installation is active with all required permissions",
            "Repair or add an App installation, then rerun `yoke github status`.",
        )
    return _binding(
        VERDICT_OK,
        "the App grants installation access with the required permissions",
        "",
    )


def _binding(verdict: str, message: str, hint: str) -> dict[str, str]:
    binding = {"verdict": verdict, "message": message}
    if hint:
        binding["hint"] = hint
    return binding


__all__ = [
    "MergePathSelection",
    "READINESS_BINDINGS",
    "RECONNECT_RECOVERY",
    "RETRY_RECOVERY",
    "VERDICT_BROKEN",
    "VERDICT_BUSY",
    "VERDICT_OK",
    "VERDICT_UNPROVEN",
    "app_installation_binding",
    "git_access_token_binding",
    "resolve_selection",
    "status_connection_scope",
    "user_authorization_binding",
]
