"""CLI coverage for verified GitHub App repository binding."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_cli.commands.adapters import project_github_binding


def test_bind_uses_cached_user_authorization_and_narrow_intent(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        project_github_binding.machine_config,
        "github_config",
        lambda: {"api_url": "https://github.example/api/v3"},
    )
    monkeypatch.setattr(
        project_github_binding.github_user_tokens,
        "access_token_from_machine_config",
        lambda: SimpleNamespace(access_token="transient-user-token"),
    )

    def _dispatch(function_id, payload, session_id, json_mode):
        captured.update({
            "function_id": function_id,
            "payload": payload,
            "session_id": session_id,
            "json_mode": json_mode,
        })
        return 0

    monkeypatch.setattr(project_github_binding, "_dispatch", _dispatch)

    result = project_github_binding.projects_github_binding_bind([
        "--project", "buzz",
        "--installation-id", "101",
        "--repository-id", "202",
        "--github-repo", "Example/Buzz",
        "--json",
    ])

    assert result == 0
    assert captured == {
        "function_id": "projects.github_binding.bind",
        "payload": {
            "project": "buzz",
            "installation_id": "101",
            "repository_id": "202",
            "github_repo": "Example/Buzz",
            "expected_api_url": "https://github.example/api/v3",
            "github_user_access_token": "transient-user-token",
        },
        "session_id": None,
        "json_mode": True,
    }


def test_bind_reports_reauthorization_without_dispatch(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        project_github_binding.machine_config,
        "github_config",
        lambda: {"api_url": "https://api.github.com"},
    )
    def _missing_token():
        raise project_github_binding.github_user_tokens.GitHubUserTokenError(
            "authorization expired at /private/secrets/github-user.json"
        )

    monkeypatch.setattr(
        project_github_binding.github_user_tokens,
        "access_token_from_machine_config",
        _missing_token,
    )
    monkeypatch.setattr(
        project_github_binding,
        "_dispatch",
        lambda *_args: (_ for _ in ()).throw(AssertionError("must not dispatch")),
    )

    result = project_github_binding.projects_github_binding_bind([
        "--project", "buzz",
        "--installation-id", "101",
        "--repository-id", "202",
        "--github-repo", "example/buzz",
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
        "--project", "buzz", "--field", "github_repo",
    ])

    assert result == 0
    assert captured == {
        "function_id": "projects.github_binding.status",
        "payload": {"project": "buzz"},
        "field": "github_repo",
    }
