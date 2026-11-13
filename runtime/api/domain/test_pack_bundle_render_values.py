"""Pack bundles validate only the value groups their version consumes."""

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


@pytest.mark.parametrize("key", ["project_name", "web_port", "preview_namespace"])
def test_project_values_ignore_unrelated_invalid_delivery_settings(
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




@pytest.mark.parametrize("key", ["state_bucket", "runner_fleet_aws_region"])
def test_retired_pulumi_values_are_not_pack_values(tmp_path, incomplete_settings, key):
    write_pack(tmp_path, files={"docs/packs/sample/README.md": "{{" + key + "}}"})
    with pytest.raises(pack_catalog.PackError, match="unavailable render values"):
        pack_catalog.build_pack_bundle(
            object(),
            project="sample",
            pack="sample",
            packs_dir=tmp_path / "packs",
        )
