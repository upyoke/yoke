"""A CI-gated release on a private repository reads with the access it needs.

A private repository answers its commits and comparisons only to a token
scoped to ``contents: read``; the fake GitHub here enforces exactly that, so
these tests fail if creation mints its CI-gate token with less.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from yoke_core.domain import deployment_run_ci_tested_source as tested
from yoke_core.domain import deployment_run_gate_branch_lineage as lineage
from yoke_core.domain.deployment_run_ci_gate_github import CI_GATE_READ_PERMISSIONS
from yoke_core.domain.gh_rest_transport import RestAuthError

HEAD, TESTED = "c" * 40, "a" * 40
REPO = "owner/platform"
COMMITS = [
    {"sha": HEAD, "parents": [{"sha": TESTED}]},
    {"sha": TESTED, "parents": []},
]
RUNS = [
    {
        "id": 1,
        "run_number": 1,
        "head_sha": TESTED,
        "head_branch": "main",
        "event": "push",
        "status": "completed",
        "conclusion": "success",
    }
]


def _private_github(path: str, *, query=None, token: str):
    """Answer like a private repo: Contents reads need a contents-scoped token."""
    scopes = set(token.split(","))
    if path.endswith("/commits") or "/compare/" in path:
        if "contents" not in scopes:
            raise RestAuthError(
                "HTTP 403: Resource not accessible by integration", status=403
            )
        return COMMITS if path.endswith("/commits") else {"status": "ahead"}
    assert "actions" in scopes
    wanted = (query or {}).get("head_sha")
    return {"workflow_runs": [r for r in RUNS if not wanted or r["head_sha"] == wanted]}


def _scoped_auth(project, *, required_permissions):
    """Mint a token that carries exactly the permissions it was scoped to."""
    return SimpleNamespace(token=",".join(sorted(required_permissions)), repo=REPO)


@pytest.fixture
def private_repo():
    gating = [{"step_runner": "github-actions-workflow"}]
    with (
        mock.patch.object(
            tested, "_flow_facts", return_value=(gating, "persistent", "prod")
        ),
        mock.patch(
            "yoke_core.domain.project_renderer_settings.project_ci_workflow_file",
            return_value="platform-ci.yml",
        ),
        mock.patch(
            "yoke_core.domain.project_checkout_locations.checkout_for_project_slug",
            return_value="/checkout",
        ),
        mock.patch(
            "yoke_core.domain.deploy_pipeline_gates.resolve_flow_gate_branch",
            return_value="main",
        ),
        mock.patch(
            "yoke_core.domain.project_github_auth.resolve_project_github_auth",
            side_effect=_scoped_auth,
        ),
        mock.patch(
            "yoke_core.domain.github_actions_rest.rest_get", side_effect=_private_github
        ),
        mock.patch.object(lineage, "previous_release", return_value=None),
    ):
        yield


def test_the_ci_gate_token_is_scoped_to_actions_and_contents_read():
    assert dict(CI_GATE_READ_PERMISSIONS) == {"actions": "read", "contents": "read"}


def test_create_without_a_source_binds_the_newest_tested_commit(private_repo):
    bound = tested.bind_tested_release_source("platform", "flow", "prod", None)

    assert bound == TESTED


def test_an_untested_source_refuses_naming_the_newest_tested_commit(private_repo):
    with pytest.raises(tested.ReleaseSourceRefused) as refused:
        tested.bind_tested_release_source("platform", "flow", "prod", HEAD)

    assert refused.value.code == tested.UNTESTED
    message = str(refused.value)
    assert f"newest commit with its own passing or running run is {TESTED}" in message
    assert f"omit --source-ref to bind {TESTED}" in message


@pytest.mark.parametrize(
    "read",
    [
        lambda target: tested.newest_tested_commit(target),
        lambda target: lineage._compare_status(target, TESTED, HEAD),
    ],
    ids=["commits", "compare"],
)
def test_an_authorization_refusal_names_the_access_and_repair_not_retry(read):
    target = tested.CiGateTarget(
        "platform", "flow", REPO, "platform-ci.yml", "main", "actions"
    )
    with (
        mock.patch(
            "yoke_core.domain.github_actions_rest.rest_get", side_effect=_private_github
        ),
        pytest.raises(tested.ReleaseSourceRefused) as refused,
    ):
        read(target)

    assert refused.value.code == tested.UNVERIFIABLE
    message = str(refused.value)
    assert "HTTP 403" in message
    assert "actions: read, contents: read" in message
    assert "Repair: approve missing App permissions for project platform" in message
    assert "Retry the create" not in message
