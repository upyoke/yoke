"""CLI coverage for verified GitHub App repository binding."""

from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from yoke_cli.commands.adapters import project_github_binding


def test_bind_uses_cached_user_authorization_and_narrow_intent(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        project_github_binding.github_binding_auth,
        "locked_profile_bound_access_for_binding",
        lambda: nullcontext(SimpleNamespace(
            api_url="https://github.example/api/v3",
            token=SimpleNamespace(access_token="transient-user-token"),
        )),
    )

    def _dispatch(
        function_id, payload, session_id, json_mode, *, sensitive_values=(),
    ):
        captured.update({
            "function_id": function_id,
            "payload": payload,
            "session_id": session_id,
            "json_mode": json_mode,
            "sensitive_values": sensitive_values,
        })
        return 0

    monkeypatch.setattr(project_github_binding, "_dispatch", _dispatch)

    result = project_github_binding.projects_github_binding_bind([
        "--project", "externalwebapp",
        "--installation-id", "101",
        "--repository-id", "202",
        "--github-repo", "Example/ExternalWebapp",
        "--json",
    ])

    assert result == 0
    assert captured == {
        "function_id": "projects.github_binding.bind",
        "payload": {
            "project": "externalwebapp",
            "installation_id": "101",
            "repository_id": "202",
            "github_repo": "Example/ExternalWebapp",
            "expected_api_url": "https://github.example/api/v3",
            "github_user_access_token": "transient-user-token",
        },
        "session_id": None,
        "json_mode": True,
        "sensitive_values": ("transient-user-token",),
    }


def test_bind_reports_reauthorization_without_dispatch(monkeypatch, capsys) -> None:
    def _missing_token():
        raise project_github_binding.github_binding_auth.GitHubBindingAuthError(
            "authorization expired at /private/secrets/github-user.json"
        )

    monkeypatch.setattr(
        project_github_binding.github_binding_auth,
        "locked_profile_bound_access_for_binding",
        lambda: nullcontext(_missing_token()),
    )
    monkeypatch.setattr(
        project_github_binding,
        "_dispatch",
        lambda *_args: (_ for _ in ()).throw(AssertionError("must not dispatch")),
    )

    result = project_github_binding.projects_github_binding_bind([
        "--project", "externalwebapp",
        "--installation-id", "101",
        "--repository-id", "202",
        "--github-repo", "example/externalwebapp",
    ])

    assert result == 1
    error = capsys.readouterr().err
    assert "yoke github connect" in error
    assert "/private/secrets/github-user.json" not in error


def test_status_can_select_verified_repository_field(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def _dispatch(function_id, payload, session_id, json_mode, *, field=None):
        captured.update({
            "function_id": function_id,
            "payload": payload,
            "field": field,
        })
        return 0

    monkeypatch.setattr(project_github_binding, "_dispatch", _dispatch)

    result = project_github_binding.projects_github_binding_status([
        "--project", "externalwebapp", "--field", "github_repo",
    ])

    assert result == 0
    assert captured == {
        "function_id": "projects.github_binding.status",
        "payload": {"project": "externalwebapp"},
        "field": "github_repo",
    }
