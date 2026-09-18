"""Typed container-registry lifecycle flag: canonicalize and registry render."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.project_renderer_pulumi_stack_config import (
    _RENDER_KEYS_BY_KIND,
    _legacy_render_values,
    _selected_render_values,
)
from yoke_core.domain.project_renderer_pulumi_values import gather_pulumi_values
from yoke_core.domain.projects_capability_settings_validation import (
    canonicalize_capability_settings,
)
from runtime.api.domain.test_project_renderer_pulumi import (
    _make_project_root,
    _settings_from_context,
    _stub_renderer_settings,
)


def test_absent_document_stays_valid():
    canonical = canonicalize_capability_settings(
        "container-registry", json.dumps({"repository": "yoke-core"})
    )
    assert json.loads(canonical) == {"repository": "yoke-core"}


def test_optional_bool_is_accepted():
    canonical = canonicalize_capability_settings(
        "container-registry",
        json.dumps(
            {
                "repository": "yoke-core",
                "manage_platform_image_lifecycle": True,
            }
        ),
    )
    assert json.loads(canonical)["manage_platform_image_lifecycle"] is True


def test_unknown_key_is_refused():
    with pytest.raises(ValueError, match="unknown keys"):
        canonicalize_capability_settings(
            "container-registry",
            json.dumps({"repository": "yoke-core", "extra": True}),
        )


def test_non_bool_lifecycle_is_refused():
    with pytest.raises(ValueError, match="boolean"):
        canonicalize_capability_settings(
            "container-registry",
            json.dumps(
                {
                    "repository": "yoke-core",
                    "manage_platform_image_lifecycle": "true",
                }
            ),
        )


def test_gather_defaults_lifecycle_false(tmp_path, monkeypatch):
    _stub_renderer_settings(monkeypatch, "yoke", {"projectName": "yoke"})
    values = gather_pulumi_values("yoke", _make_project_root(tmp_path, "yoke"))
    assert values["manage_platform_image_lifecycle"] == "false"


def test_gather_emits_true_when_set(tmp_path, monkeypatch):
    settings = _stub_renderer_settings(
        monkeypatch, "yoke", {"projectName": "yoke"}
    )
    settings.capabilities["container-registry"][
        "manage_platform_image_lifecycle"
    ] = True
    values = gather_pulumi_values(
        "yoke", _make_project_root(tmp_path, "yoke"), settings
    )
    assert values["manage_platform_image_lifecycle"] == "true"


def test_registry_allowlist_includes_lifecycle_key():
    assert "manage_platform_image_lifecycle" in _RENDER_KEYS_BY_KIND["registry"]


def test_selected_render_keeps_absent_default_and_true():
    false_values = _selected_render_values(
        "registry",
        {
            "aws_account_id": "1",
            "aws_region": "us-east-1",
            "manage_platform_image_lifecycle": "false",
            "repository_name": "yoke-core",
        },
    )
    assert false_values["manage_platform_image_lifecycle"] == "false"
    true_values = _selected_render_values(
        "registry",
        {
            "aws_account_id": "1",
            "aws_region": "us-east-1",
            "manage_platform_image_lifecycle": "true",
            "repository_name": "yoke-core",
        },
    )
    assert true_values["manage_platform_image_lifecycle"] == "true"


def test_legacy_registry_render_defaults_false():
    settings = _settings_from_context("yoke", {"projectName": "yoke"})
    rendered = _legacy_render_values(
        "registry", {"aws_region": "us-east-1"}, settings, ["registry"]
    )
    assert rendered["manage_platform_image_lifecycle"] == "false"
    assert rendered["repository_name"] == "yoke-core"
