"""Setup reuses only the exact active project binding before attempting bind."""

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from yoke_cli.config import project_onboard_progress as mod


@pytest.mark.parametrize(
    ("binding", "status_fails", "bind_expected"),
    [
        ({"status": "active", "installation_id": "123", "repository_id": "456"}, False, False),
        ({"status": "active", "installation_id": "999", "repository_id": "456"}, False, True),
        ({"status": "active", "installation_id": "123", "repository_id": "999"}, False, True),
        ({"status": "pending_permission", "installation_id": "123", "repository_id": "456"}, False, True),
        (None, False, True),
        (None, True, True),
    ],
)
def test_store_binding_checks_exact_active_identity(
    tmp_path, monkeypatch, binding, status_fails, bind_expected,
):
    repository = {
        "installation_id": 123, "repository_id": 456, "full_name": "owner/demo",
    }
    monkeypatch.setattr(
        mod.machine_config, "github_config",
        lambda _: {"repositories": [repository]},
    )
    monkeypatch.setattr(
        mod.github_binding_auth, "locked_profile_bound_access_for_binding",
        lambda **_: nullcontext(SimpleNamespace(
            api_url="https://api.github.example",
            token=SimpleNamespace(access_token="test-token"),
        )),
    )
    calls = []
    active = {
        "binding": {"status": "active", "installation_id": "123", "repository_id": "456"},
        "permission_status": {"satisfied": True},
    }

    def dispatch(function_id, payload, config_path, **kwargs):
        calls.append((function_id, payload))
        if function_id == "projects.github_binding.status":
            assert payload == {"project": "41"}
            if status_fails:
                raise mod.github_binding_auth.GitHubBindingAuthError("status unavailable")
            return {"binding": binding, "permission_status": {"satisfied": True}}
        assert function_id == "projects.github_binding.bind"
        assert payload["installation_id"] == 123
        assert payload["repository_id"] == 456
        assert kwargs["sensitive_values"] == ("test-token",)
        return active

    monkeypatch.setattr(mod, "dispatch", dispatch)
    adoption = {"choice": "app-binding", "github_repo": "owner/demo"}
    result = mod.store_github_binding(
        None, "app-binding", {"id": 41, "slug": "demo"}, adoption,
        tmp_path / "config.json",
    )
    assert [call[0] for call in calls] == ["projects.github_binding.status"] + (
        ["projects.github_binding.bind"] if bind_expected else []
    )
    assert result["binding"] == "active"
    assert result["permission_status"] == {"satisfied": True}
    assert adoption == {"choice": "app-binding", "github_repo": "owner/demo"}
