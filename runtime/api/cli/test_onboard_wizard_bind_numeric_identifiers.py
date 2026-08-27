"""The wizard's bind step sends GitHub's numeric ids straight to the contract."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

from yoke_cli.config import project_onboard_progress
from yoke_core.domain.handlers.project_github_binding import (
    ProjectGithubBindingBindRequest,
)


def _install_wizard_github_authority(monkeypatch) -> None:
    """Machine config and App authorization as the wizard sees them."""

    monkeypatch.setattr(
        project_onboard_progress.machine_config,
        "github_config",
        lambda _path: {
            "api_url": "https://api.github.example",
            "repositories": [
                {
                    "installation_id": 123,
                    "repository_id": 456,
                    "full_name": "owner/demo",
                }
            ],
        },
    )
    monkeypatch.setattr(
        project_onboard_progress.github_binding_auth,
        "locked_profile_bound_access_for_binding",
        lambda **_kwargs: nullcontext(
            SimpleNamespace(
                api_url="https://api.github.example",
                token=SimpleNamespace(access_token="ghu_short_lived"),
            )
        ),
    )


def test_wizard_bind_step_payload_satisfies_the_registered_contract(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _install_wizard_github_authority(monkeypatch)
    parsed_binds: list[ProjectGithubBindingBindRequest] = []

    def dispatch_through_contract(function_id, payload, _config_path, **_kwargs):
        if function_id != "projects.github_binding.bind":
            return {}
        # The registered handler parses this exact payload; a numeric GitHub
        # id refused here is the live wizard failure.
        parsed_binds.append(ProjectGithubBindingBindRequest(**payload))
        return {"binding": {"status": "active"}, "permission_status": {}}

    monkeypatch.setattr(project_onboard_progress, "dispatch", dispatch_through_contract)

    outcome = project_onboard_progress.store_github_binding(
        None,
        "app-binding",
        {"id": 41, "slug": "demo", "name": "Demo"},
        {"choice": "app-binding", "github_repo": "owner/demo"},
        tmp_path / "config.json",
        persist_sync_mode=True,
    )

    assert [
        (bind.installation_id, bind.repository_id, bind.project)
        for bind in parsed_binds
    ] == [("123", "456", "41")]
    assert outcome["binding"] == "active"
    assert outcome["mode"] == "enabled"
