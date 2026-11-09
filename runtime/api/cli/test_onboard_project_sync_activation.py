from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli.config import project_onboard_progress


@pytest.mark.parametrize(
    ("binding_status", "expected_functions", "expected_mode"),
    [
        (
            "active",
            ["projects.github_binding.status", "projects.github_binding.bind"],
            "disabled",
        ),
        ("pending", ["projects.github_binding.status", "projects.github_binding.bind"], "disabled"),
    ],
)
@pytest.mark.parametrize("persist_sync_mode", [True, False])
def test_app_binding_never_opts_into_issue_sync(
    tmp_path: Path,
    monkeypatch,
    binding_status: str,
    expected_functions: list[str],
    expected_mode: str,
    persist_sync_mode: bool,
) -> None:
    calls: list[tuple[str, dict]] = []
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

    def dispatch(function_id, payload, _config_path, **_kwargs):
        calls.append((function_id, payload))
        if function_id == "projects.github_binding.status":
            return {"binding": None}
        if function_id == "projects.github_binding.bind":
            return {"binding": {"status": binding_status}}
        return {"project": payload}

    monkeypatch.setattr(project_onboard_progress, "dispatch", dispatch)

    report = project_onboard_progress.store_github_binding(
        None,
        "app-binding",
        {"id": 41, "slug": "demo", "name": "Demo"},
        {"choice": "app-binding", "github_repo": "owner/demo"},
        tmp_path / "config.json",
        persist_sync_mode=persist_sync_mode,
    )

    assert [function_id for function_id, _payload in calls] == expected_functions
    assert report["mode"] == expected_mode
