"""Verified GitHub response fixtures shared by task side-effect tests."""

from yoke_core.domain.gh_rest_transport import RestResponse
from yoke_core.domain.project_github_auth import ProjectGithubAuth


def _auth(project: str = "yoke", repo: str = "org/yoke") -> ProjectGithubAuth:
    return ProjectGithubAuth(
        project=project,
        repo=repo,
        token="t",
    )


def _ok_response(body=None) -> RestResponse:
    return RestResponse(
        status=200,
        headers={},
        body=body if body is not None else {},
    )
