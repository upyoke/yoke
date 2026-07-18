"""Bootstrap verification keeps read-only environment probes on baseline auth."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.bootstrap_project import run_verify
from yoke_core.domain.bootstrap_project_test_helpers import (
    _FakeRestResponse,
    setup_validation_ctx,
)
from yoke_core.domain.project_github_auth import ProjectGithubAuth


def test_verify_uses_baseline_token_for_secrets_and_environment_listing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    resolver_calls: list[dict[str, object]] = []
    authorizations: list[tuple[str, str | None]] = []

    def fake_resolve(project: str, **kwargs) -> ProjectGithubAuth:
        resolver_calls.append(dict(kwargs))
        return ProjectGithubAuth(
            project=project,
            repo="example-org/externalwebapp",
            token="ghs_baseline_token",
            installation_id="12345",
        )

    def fake_urlopen(request, timeout):
        path = request.full_url.split("api.github.com", 1)[-1]
        authorizations.append((path, request.get_header("Authorization")))
        if "/actions/secrets" in path:
            names = ("EXT_SSH_KEY", "EXT_SSH_HOST", "EXT_SSH_USER")
            return _FakeRestResponse(
                200, {"secrets": [{"name": name} for name in names]},
            )
        if path.endswith("/environments"):
            return _FakeRestResponse(
                200, {"environments": [{"name": "production"}]},
            )
        return _FakeRestResponse(200, {})

    monkeypatch.setattr(
        "yoke_core.domain.bootstrap_project_verify.resolve_project_github_auth",
        fake_resolve,
    )
    monkeypatch.setattr(
        "yoke_core.domain.bootstrap_project_verify._expected_workflow_names",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        "yoke_core.domain.gh_rest_transport.urlopen", fake_urlopen,
    )

    with setup_validation_ctx(tmp_path) as (ctx, _db_path, _ssh_key):
        assert run_verify(
            ctx,
            github_repo="example-org/externalwebapp",
            display_name="ExternalWebapp",
        ) == 0

    assert len(resolver_calls) == 1
    assert dict(resolver_calls[0]["required_permissions"]) == {
        "actions": "read",
        "contents": "read",
        "secrets": "read",
    }
    assert [
        auth for path, auth in authorizations if "/actions/secrets" in path
    ] == ["Bearer ghs_baseline_token"]
    assert [
        auth for path, auth in authorizations if path.endswith("/environments")
    ] == ["Bearer ghs_baseline_token"]


def test_verify_rejects_repository_override_outside_binding(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    def fake_resolve(project: str, **_kwargs) -> ProjectGithubAuth:
        return ProjectGithubAuth(
            project=project,
            repo="example-org/verified",
            token="ghs_baseline_token",
        )

    monkeypatch.setattr(
        "yoke_core.domain.bootstrap_project_verify.resolve_project_github_auth",
        fake_resolve,
    )
    with setup_validation_ctx(tmp_path) as (ctx, _db_path, _ssh_key):
        assert run_verify(ctx, github_repo="example-org/stale") == 1

    assert "does not match" in capsys.readouterr().out
