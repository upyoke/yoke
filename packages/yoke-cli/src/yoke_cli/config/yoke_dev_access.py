"""Access checks for the "Develop Yoke itself" onboarding flow.

Developing Yoke needs two independent grants the wizard verifies before it
sets the source checkout up: the connected Yoke token must reach Yoke's own
project in the Yoke core database, and a GitHub PAT must be able to read Yoke's
GitHub repo. Both checks live here behind small functions so the wizard drives
them while tests mock the network at one seam each.

Neither check imports ``yoke_core``: the Yoke-project check relays a
``projects.list`` function call to the connected API over the existing
``transport.https`` seam, and the GitHub-repo check reuses the read-only
machine verifier. The product onboarding boundary stays intact.
"""

from __future__ import annotations

import uuid

from yoke_cli.config import db_admin_setup
from yoke_cli.config import github_machine_verify
from yoke_cli.config import secrets as machine_secrets
from yoke_cli.transport.https import HttpsConnection, relay_https
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

# Yoke's own core database project slug — the single source the db-admin setup
# already keys its default project on. Developing Yoke means having access to this
# project.
YOKE_PROJECT_SLUG = db_admin_setup.DEFAULT_PROJECT

# Yoke's canonical GitHub repo (OWNER/REPO). The homebrew formula homepage
# (packaging/homebrew/Formula/yoke.rb.in) names the same repo; this is the
# single Python-importable source for the slug the dev flow's GitHub check uses.
YOKE_GITHUB_REPO = "upyoke/yoke"


class YokeDevAccessError(RuntimeError):
    """A develop-Yoke access check failed; the message is shown to the user."""


def resolve_yoke_token(token: str | None, token_file: str | None) -> str | None:
    """Resolve the connected Yoke API token from the pasted value or a file.

    Returns ``None`` when the machine was never connected to a Yoke API
    (neither a pasted token nor a token file), so the caller can say so instead
    of probing with an empty credential.
    """
    if token:
        return token
    if token_file:
        try:
            return machine_secrets.read_secret_file(token_file, "Yoke API token")
        except machine_secrets.MachineSecretError as exc:
            raise YokeDevAccessError(str(exc)) from exc
    return None


def yoke_project_reachable(api_url: str, token: str) -> bool:
    """True when the connected Yoke token can list Yoke's own project.

    Relays a ``projects.list`` call to the connected API and checks the visible
    rows for the Yoke project slug. ``projects.list`` is a global read with no
    work claim, so a synthetic onboarding session id is sufficient — the server
    resolves the actor from the bearer token. A transport or boundary failure
    raises :class:`YokeDevAccessError` so the caller renders the reason.
    """
    request = FunctionCallRequest(
        function="projects.list",
        actor=ActorContext(session_id=f"onboard-dev-check-{uuid.uuid4().hex}"),
        target=TargetRef(kind="global"),
        payload={},
    )
    response = relay_https(request, HttpsConnection(api_url=api_url, token=token))
    if not response.success:
        error = response.error
        detail = error.message if error else "the Yoke API call failed"
        raise YokeDevAccessError(detail)
    rows = response.result.get("rows") or []
    return any(
        isinstance(row, dict) and row.get("slug") == YOKE_PROJECT_SLUG
        for row in rows
    )


def github_can_reach_yoke_repo(api_url: str, token: str) -> bool:
    """True when the GitHub PAT can read Yoke's repo.

    Reuses the read-only machine verifier: passing ``github_repo`` makes it hit
    ``/repos/{owner}/{repo}``, which raises for a token that cannot reach the
    repo. A reachable repo returns an ``access.requested_repo.ok`` summary.
    """
    try:
        report = github_machine_verify.verify(
            api_url, token, github_repo=YOKE_GITHUB_REPO,
        )
    except github_machine_verify.GitHubMachineVerificationError:
        return False
    requested = report.get("access", {}).get("requested_repo")
    return bool(isinstance(requested, dict) and requested.get("ok"))


__all__ = [
    "YOKE_GITHUB_REPO",
    "YOKE_PROJECT_SLUG",
    "YokeDevAccessError",
    "github_can_reach_yoke_repo",
    "resolve_yoke_token",
    "yoke_project_reachable",
]
