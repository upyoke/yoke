"""Environment probes retain Actions read and distinguish unreadable from absent."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_core.domain import bootstrap_project_verify as bootstrap
from yoke_core.domain import validate_webapp_pipeline_checks_remote as validator
from yoke_core.domain.gh_rest_transport_errors import RestAuthError
from yoke_core.domain.project_github_auth import ProjectGithubAuth
from yoke_core.domain.validate_webapp_pipeline_helpers import Counters, ValidateContext


def _run_probe(monkeypatch, tmp_path, consumer, private, outcome):
    module = bootstrap if consumer == "bootstrap" else validator
    repo = f"example-org/{'private' if private else 'public'}-webapp"
    requested_permissions = []
    environment_requests = []
    identity = SimpleNamespace(id=1, slug="webapp", name="Webapp")
    monkeypatch.setattr(module, "_connect", lambda *_: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(module, "_resolve_project_identity", lambda *_: identity)

    def resolve(project, **kwargs):
        permissions = dict(kwargs["required_permissions"])
        requested_permissions.append(permissions)
        return ProjectGithubAuth(project=project, repo=repo, token="installation-token")

    def request(req, *, token):
        if req.path.endswith("/environments"):
            environment_requests.append(req.path)
            # A public endpoint can hide a scope bug; the private fake enforces it.
            if private and requested_permissions[-1].get("actions") != "read":
                raise RestAuthError("Resource not accessible by integration", status=403)
            assert token == "installation-token"
            if outcome == "refused":
                raise RestAuthError("Resource not accessible by integration", status=403)
            body = {
                "present": {"environments": [{"name": "prod"}]},
                "empty": {"environments": []},
                "hidden": {},
                "malformed": {"environments": None},
                "hidden_name": {"environments": [{"name": "prod"}, {}]},
            }[outcome]
        elif req.path.endswith("/actions/secrets"):
            body = {"secrets": [{"name": f"WEBAPP_{suffix}"} for suffix in (
                "SSH_KEY", "SSH_HOST", "SSH_USER",
            )]}
        else:
            body = {}
        return SimpleNamespace(body=body)

    monkeypatch.setattr(module, "resolve_project_github_auth", resolve)
    monkeypatch.setattr(module.gh_rest_transport, "request_with_retry", request)
    if consumer == "bootstrap":
        monkeypatch.setattr(bootstrap, "_query_scalar", lambda *_: "Webapp")
        monkeypatch.setattr(bootstrap.helpers, "_p", lambda *_: "?")
        monkeypatch.setattr(bootstrap, "_capability_settings", lambda *_: {})
        monkeypatch.setattr(bootstrap, "_expected_workflow_names", lambda *_: [])
        ctx = SimpleNamespace(project="webapp", project_upper="WEBAPP")
        result = bootstrap.run_verify(ctx, display_name="Webapp")
        assert result == (0 if outcome == "present" else 1)
    else:
        marker = tmp_path / "control-plane"
        marker.touch()
        ctx = ValidateContext(
            project_root=tmp_path, script_dir=tmp_path, control_plane_marker=marker,
            project="webapp",
        )
        validator._check_github_actions_infrastructure(ctx, Counters(), "", repo)
    assert len(environment_requests) == 1
    assert len(requested_permissions) == 1
    assert requested_permissions[0] == {
        "actions": "read", "secrets": "read",
        **({"contents": "read"} if consumer == "bootstrap" else {}),
    }


@pytest.mark.parametrize("consumer", ["bootstrap", "validator"])
@pytest.mark.parametrize("private", [False, True], ids=["public", "private"])
def test_environment_listing_requests_actions_read(
    monkeypatch, tmp_path, capsys, consumer, private,
):
    _run_probe(monkeypatch, tmp_path, consumer, private, "present")
    out = capsys.readouterr().out
    expected = (
        "[PASS] Environment: prod" if consumer == "bootstrap"
        else "GitHub environment 'prod' exists"
    )
    assert expected in out


@pytest.mark.parametrize("consumer", ["bootstrap", "validator"])
@pytest.mark.parametrize("outcome", ["refused", "hidden", "malformed", "hidden_name"])
def test_unreadable_environments_fail_loudly(
    monkeypatch, tmp_path, capsys, consumer, outcome,
):
    _run_probe(monkeypatch, tmp_path, consumer, True, outcome)
    out = capsys.readouterr().out
    assert "unreadable" in out
    assert "[PASS] Environment:" not in out
    assert "GitHub environment 'prod' exists" not in out
    assert "none registered" not in out
    assert "environment 'prod' not found" not in out
    if outcome == "refused":
        assert "Resource not accessible by integration" in out


@pytest.mark.parametrize("consumer", ["bootstrap", "validator"])
def test_readable_empty_environments_report_absence(
    monkeypatch, tmp_path, capsys, consumer,
):
    _run_probe(monkeypatch, tmp_path, consumer, True, "empty")
    out = capsys.readouterr().out
    assert "unreadable" not in out
    expected = (
        "none registered" if consumer == "bootstrap"
        else "environment 'prod' not found"
    )
    assert expected in out
