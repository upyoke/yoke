"""Pack bundles validate only the renderer groups their version consumes."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from runtime.api.domain.pack_catalog_test_support import write_pack
from yoke_core.domain import pack_catalog
from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    RendererEnvironmentSettings,
)


ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def incomplete_settings(monkeypatch):
    settings = ProjectRendererSettings(
        project="sample",
        deploy_namespace="sample",
        display_name="Sample",
        site_id="1",
        site_settings={},
        primary_environment=None,
        environments=(
            RendererEnvironmentSettings(
                id="1",
                name="prod",
                settings={"delivery_authority": "invalid"},
            ),
        ),
        capabilities={
            "pulumi-state": {"stacks": ["runner-fleet"]},
            "aws-admin": {"region": "us-east-1"},
        },
    )
    monkeypatch.setattr(pack_catalog, "server_tree_root", lambda: ROOT)
    monkeypatch.setattr(
        pack_catalog,
        "resolve_project",
        lambda *args, **kwargs: SimpleNamespace(id=9, slug="sample"),
    )
    monkeypatch.setattr(
        pack_catalog,
        "_load_project_renderer_settings",
        lambda *args: settings,
    )
    return settings


def test_structured_events_ignores_unrelated_incomplete_settings(incomplete_settings):
    bundle = pack_catalog.build_pack_bundle(
        object(),
        project="sample",
        pack="structured-events",
        version="5.1.0",
    )
    assert bundle["render_values"] == {"project_name": "sample"}
    assert bundle["files"]


@pytest.mark.parametrize(
    "key",
    [
        "state_bucket",
        "pulumi_runner_fleet_stack_name",
        "github_api_url",
        "delivery_distribution_bucket_names_json",
    ],
)
def test_other_groups_ignore_unrelated_invalid_settings(
    tmp_path,
    incomplete_settings,
    key,
):
    write_pack(tmp_path, files={"docs/packs/sample/README.md": "{{" + key + "}}"})
    bundle = pack_catalog.build_pack_bundle(
        object(),
        project="sample",
        pack="sample",
        packs_dir=tmp_path / "packs",
    )
    assert set(bundle["render_values"]) == {key}
    assert bundle["render_values"][key]


@pytest.mark.parametrize(
    ("key", "setting"),
    [
        ("runner_fleet_aws_region", "github_capability"),
        ("delivery_authority_json", "delivery_authority"),
    ],
)
def test_required_invalid_settings_raise_pack_error_with_repair(
    tmp_path,
    incomplete_settings,
    key,
    setting,
):
    write_pack(tmp_path, files={"docs/packs/sample/README.md": "{{" + key + "}}"})
    with pytest.raises(pack_catalog.PackError) as error:
        pack_catalog.build_pack_bundle(
            object(),
            project="sample",
            pack="sample",
            packs_dir=tmp_path / "packs",
        )
    assert "pack_render_settings_invalid" in str(error.value)
    assert setting in str(error.value)
    assert "yoke projects capability-settings set" in str(error.value)
    assert "yoke projects environment-settings merge" in str(error.value)


def test_required_delivery_authority_renders_valid_settings(
    tmp_path,
    monkeypatch,
    incomplete_settings,
):
    settings = replace(
        incomplete_settings,
        environments=(
            RendererEnvironmentSettings(
                id="1",
                name="prod",
                settings={"delivery_authority": {"documents": ["Deploy"]}},
            ),
        ),
    )
    monkeypatch.setattr(
        pack_catalog,
        "_load_project_renderer_settings",
        lambda *args: settings,
    )
    write_pack(
        tmp_path,
        files={
            "docs/packs/sample/README.md": "{{delivery_authority_json}}",
        },
    )
    bundle = pack_catalog.build_pack_bundle(
        object(),
        project="sample",
        pack="sample",
        packs_dir=tmp_path / "packs",
    )
    assert (
        '"documents":["Deploy"]' in bundle["render_values"]["delivery_authority_json"]
    )


def test_bundle_handler_returns_named_refusal_for_required_runner_settings(
    tmp_path,
    monkeypatch,
    incomplete_settings,
):
    from yoke_contracts.api.function_call import (
        ActorContext,
        FunctionCallRequest,
        TargetRef,
    )
    from yoke_core.domain.handlers import pack_handlers

    write_pack(
        tmp_path,
        files={
        "docs/packs/sample/README.md": "{{runner_fleet_aws_region}}",
        },
    )
    monkeypatch.setattr(pack_catalog, "server_tree_root", lambda: tmp_path)
    monkeypatch.setattr(
        pack_handlers.db_helpers,
        "connect",
        lambda: SimpleNamespace(close=lambda: None),
    )
    request = FunctionCallRequest(
        function="packs.bundle.get",
        actor=ActorContext(actor_id="operator", session_id="session"),
        target=TargetRef(kind="global"),
        payload={"project": "sample", "pack": "sample"},
    )
    outcome = pack_handlers.handle_packs_bundle_get(request)
    assert outcome.primary_success is False
    assert outcome.error.code == "pack_bundle_failed"
    assert "github_capability" in outcome.error.message
