from __future__ import annotations

import pytest

from runtime.api.cli.project_onboarding_test_helpers import ProjectOnboardApi
from yoke_cli.config import existing_project_lookup


def test_find_by_github_repo_returns_existing_project_by_numeric_id() -> None:
    with ProjectOnboardApi(
        project={
            "id": 37,
            "slug": "buzz",
            "name": "Buzz",
            "github_repo": "example-org/buzz",
            "default_branch": "main",
            "public_item_prefix": "BUZZ",
        },
    ) as api:
        project = existing_project_lookup.find_by_github_repo(
            api_url=api.url,
            token="product-token",
            github_repo="git@github.com:example-org/buzz.git",
        )

    assert project == existing_project_lookup.ExistingProject(
        id=37,
        slug="buzz",
        name="Buzz",
        github_repo="example-org/buzz",
        default_branch="main",
        public_item_prefix="BUZZ",
    )
    call = api.function_call("projects.resolve_by_github_repo")
    assert call["payload"] == {"github_repo": "example-org/buzz"}


def test_find_by_project_id_returns_existing_project() -> None:
    with ProjectOnboardApi(
        project={
            "id": 37,
            "slug": "buzz",
            "name": "Buzz",
            "github_repo": "example-org/buzz",
            "default_branch": "main",
            "public_item_prefix": "BUZZ",
        },
    ) as api:
        project = existing_project_lookup.find_by_project_id(
            api_url=api.url,
            token="product-token",
            project_id=37,
        )

    assert project.id == 37
    call = api.function_call("projects.get")
    assert call["payload"] == {"project": "37"}


def test_find_by_project_id_blocks_when_project_is_not_visible() -> None:
    with ProjectOnboardApi(project_visible=False) as api:
        try:
            existing_project_lookup.find_by_project_id(
                api_url=api.url,
                token="product-token",
                project_id=41,
            )
        except existing_project_lookup.ExistingProjectAccessError as exc:
            assert "permission denied" in str(exc)
        else:  # pragma: no cover - assertion guard
            raise AssertionError("expected ExistingProjectAccessError")


def test_find_local_by_project_id_uses_local_dispatch(tmp_path, monkeypatch) -> None:
    calls = []

    def fake_call(**kwargs):
        calls.append(kwargs)
        return {
            "success": True,
            "result": {
                "row": {
                    "id": "37",
                    "slug": "buzz",
                    "name": "Buzz",
                    "github_repo": "example-org/buzz",
                    "default_branch": "main",
                    "public_item_prefix": "BUZZ",
                },
            },
        }

    monkeypatch.setattr(existing_project_lookup, "_call_local_function", fake_call)

    project = existing_project_lookup.find_local_by_project_id(
        config_path=tmp_path / "config.json",
        project_id=37,
    )

    assert project.slug == "buzz"
    assert calls == [{
        "config_path": tmp_path / "config.json",
        "function": "projects.get",
        "payload": {"project": "37"},
    }]


def test_find_local_by_project_id_accepts_local_project_without_github_repo(
    tmp_path, monkeypatch
) -> None:
    def fake_call(**kwargs):
        return {
            "success": True,
            "result": {
                "row": {
                    "id": "37",
                    "slug": "local-project",
                    "name": "Local Project",
                    "github_repo": None,
                    "default_branch": "main",
                    "public_item_prefix": "LOC",
                },
            },
        }

    monkeypatch.setattr(existing_project_lookup, "_call_local_function", fake_call)

    project = existing_project_lookup.find_local_by_project_id(
        config_path=tmp_path / "config.json",
        project_id=37,
    )

    assert project == existing_project_lookup.ExistingProject(
        id=37,
        slug="local-project",
        name="Local Project",
        github_repo="",
        default_branch="main",
        public_item_prefix="LOC",
    )


def test_find_local_by_project_id_requires_local_connection(tmp_path) -> None:
    with pytest.raises(
        existing_project_lookup.ExistingProjectLookupError,
        match="local universe connection",
    ):
        existing_project_lookup.find_local_by_project_id(
            config_path=tmp_path / "missing-config.json",
            project_id=37,
        )


def test_find_by_github_repo_returns_none_when_no_project_matches() -> None:
    with ProjectOnboardApi() as api:
        project = existing_project_lookup.find_by_github_repo(
            api_url=api.url,
            token="product-token",
            github_repo="github.com/nope/missing",
        )

    assert project is None


def test_find_by_github_repo_blocks_when_project_is_not_visible() -> None:
    with ProjectOnboardApi(project_visible=False) as api:
        try:
            existing_project_lookup.find_by_github_repo(
                api_url=api.url,
                token="product-token",
                github_repo="owner/demo",
            )
        except existing_project_lookup.ExistingProjectAccessError as exc:
            assert "does not have access" in str(exc)
        else:  # pragma: no cover - assertion guard
            raise AssertionError("expected ExistingProjectAccessError")


def test_find_local_project_reference_prefers_install_manifest(
    tmp_path, monkeypatch
) -> None:
    checkout = tmp_path / "checkout"
    (checkout / ".yoke").mkdir(parents=True)
    (checkout / ".yoke" / "install-manifest.json").write_text(
        '{"manifest_schema": 1, "project_id": 37}\n',
        encoding="utf-8",
    )

    ref = existing_project_lookup.find_local_project_reference(
        checkout,
        config_path=tmp_path / "missing-config.json",
    )

    assert ref == existing_project_lookup.LocalProjectReference(
        project_id=37,
        source=".yoke/install-manifest.json",
    )


def test_find_local_project_reference_reads_machine_config(tmp_path) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    config = tmp_path / "config.json"
    config.write_text(
        '{"schema_version": 1, "projects": {"'
        + str(checkout)
        + '": {"project_id": 37}}}\n',
        encoding="utf-8",
    )

    ref = existing_project_lookup.find_local_project_reference(
        checkout,
        config_path=config,
    )

    assert ref == existing_project_lookup.LocalProjectReference(
        project_id=37,
        source="machine config",
    )


def test_find_by_github_repo_uses_exact_resolver_not_visible_list() -> None:
    with ProjectOnboardApi() as api:
        existing_project_lookup.find_by_github_repo(
            api_url=api.url,
            token="product-token",
            github_repo="owner/demo",
        )

    assert api.function_calls("projects.list") == []
    call = api.function_call("projects.resolve_by_github_repo")
    assert call["payload"] == {
        "github_repo": "owner/demo",
    }


def test_find_by_github_repo_accepts_versioned_api_base() -> None:
    with ProjectOnboardApi(
        project={
            "id": 37,
            "slug": "buzz",
            "name": "Buzz",
            "github_repo": "example-org/buzz",
            "default_branch": "main",
            "public_item_prefix": "BUZZ",
        },
    ) as api:
        project = existing_project_lookup.find_by_github_repo(
            api_url=api.url + "/v1",
            token="product-token",
            github_repo="https://github.com/example-org/buzz.git",
        )

    assert project is not None
    assert project.slug == "buzz"
    call = api.function_call("projects.resolve_by_github_repo")
    assert len(api.requests_for("POST", "/v1/functions/call")) == 1
    assert call["payload"] == {"github_repo": "example-org/buzz"}


def test_normalize_github_repo_handles_common_clone_urls() -> None:
    assert (
        existing_project_lookup.normalize_github_repo(
            "https://github.com/Example-Org/Buzz.git"
        )
        == "example-org/buzz"
    )
    assert (
        existing_project_lookup.normalize_github_repo(
            "git@github.com:Example-Org/Buzz.git"
        )
        == "example-org/buzz"
    )
    assert existing_project_lookup.normalize_github_repo("Example-Org/Buzz") == (
        "example-org/buzz"
    )
