"""Tests for the template-bundle builder (``yoke_core.domain.template_bundle``)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_contracts.template_bundle import (
    TEMPLATE_PRODUCT_BOUNDARY_FIELD,
    TEMPLATE_PRODUCT_BOUNDARY_PRODUCT,
    TEMPLATE_PRODUCT_BOUNDARY_SOURCE_DEV_ADMIN,
)
from yoke_core.domain import template_bundle as tb


@pytest.fixture()
def server_tree(tmp_path, monkeypatch) -> Path:
    """A fake server tree with two templates; ``alpha`` carries metadata,
    a nested text file with a raw placeholder, and one binary file."""
    root = tmp_path / "tree"
    alpha = root / "templates" / "alpha"
    (alpha / "ops").mkdir(parents=True)
    (alpha / "template.json").write_text(
        json.dumps({"name": "alpha", "description": "Alpha raw material"}),
        encoding="utf-8",
    )
    (alpha / "README.md").write_text("# Alpha\n", encoding="utf-8")
    (alpha / "ops" / "deploy.yml").write_text(
        "name: {{project_name}}\n", encoding="utf-8"
    )
    (alpha / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\xff\xfe")
    beta = root / "templates" / "beta"
    beta.mkdir(parents=True)
    (beta / "notes.md").write_text("beta notes\n", encoding="utf-8")
    gamma = root / "templates" / "gamma"
    gamma.mkdir(parents=True)
    (gamma / "template.json").write_text(
        json.dumps({
            "name": "gamma",
            "description": "Gamma source-dev material",
            TEMPLATE_PRODUCT_BOUNDARY_FIELD: (
                TEMPLATE_PRODUCT_BOUNDARY_SOURCE_DEV_ADMIN
            ),
        }),
        encoding="utf-8",
    )
    (gamma / "README.md").write_text("# Gamma\n", encoding="utf-8")
    monkeypatch.setattr(tb, "server_tree_root", lambda: root)
    return root


class TestListTemplates:
    def test_lists_every_template_dir_sorted(self, server_tree) -> None:
        listing = tb.list_templates()

        assert [t["name"] for t in listing] == ["alpha", "beta", "gamma"]

    def test_description_from_template_json_when_present(self, server_tree) -> None:
        by_name = {t["name"]: t for t in tb.list_templates()}

        assert by_name["alpha"]["description"] == "Alpha raw material"
        assert by_name["beta"]["description"] == ""
        assert by_name["gamma"]["description"] == "Gamma source-dev material"

    def test_product_boundary_defaults_to_product(self, server_tree) -> None:
        by_name = {t["name"]: t for t in tb.list_templates()}

        assert by_name["alpha"][TEMPLATE_PRODUCT_BOUNDARY_FIELD] == (
            TEMPLATE_PRODUCT_BOUNDARY_PRODUCT
        )
        assert by_name["beta"][TEMPLATE_PRODUCT_BOUNDARY_FIELD] == (
            TEMPLATE_PRODUCT_BOUNDARY_PRODUCT
        )
        assert by_name["gamma"][TEMPLATE_PRODUCT_BOUNDARY_FIELD] == (
            TEMPLATE_PRODUCT_BOUNDARY_SOURCE_DEV_ADMIN
        )

    def test_file_count_counts_deliverable_text_files(self, server_tree) -> None:
        by_name = {t["name"]: t for t in tb.list_templates()}

        # template.json + README.md + ops/deploy.yml; logo.png is binary.
        assert by_name["alpha"]["file_count"] == 3
        assert by_name["beta"]["file_count"] == 1

    def test_missing_templates_dir_is_typed_error(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(tb, "server_tree_root", lambda: tmp_path / "nowhere")

        with pytest.raises(tb.TemplateBundleError):
            tb.list_templates()


class TestBuildTemplateBundle:
    def test_bundle_ships_sorted_text_files_with_placeholders_raw(
        self, server_tree
    ) -> None:
        bundle = tb.build_template_bundle("alpha")

        assert bundle["bundle_schema"] == tb.TEMPLATE_BUNDLE_SCHEMA
        assert bundle["template"] == "alpha"
        assert bundle["description"] == "Alpha raw material"
        assert bundle[TEMPLATE_PRODUCT_BOUNDARY_FIELD] == (
            TEMPLATE_PRODUCT_BOUNDARY_PRODUCT
        )
        paths = [entry["path"] for entry in bundle["files"]]
        assert paths == sorted(paths)
        assert paths == ["README.md", "ops/deploy.yml", "template.json"]
        by_path = {e["path"]: e["content"] for e in bundle["files"]}
        assert by_path["ops/deploy.yml"] == "name: {{project_name}}\n"

    def test_binary_files_are_skipped_and_counted(self, server_tree) -> None:
        bundle = tb.build_template_bundle("alpha")

        assert "logo.png" not in [e["path"] for e in bundle["files"]]
        assert bundle["binary_files_skipped"] == 1

    def test_source_dev_admin_template_requires_opt_in(self, server_tree) -> None:
        with pytest.raises(tb.TemplateAccessDeniedError):
            tb.build_template_bundle("gamma")

    def test_source_dev_admin_opt_in_builds_bundle(self, server_tree) -> None:
        bundle = tb.build_template_bundle(
            "gamma",
            include_source_dev_admin=True,
        )

        assert bundle["template"] == "gamma"
        assert bundle[TEMPLATE_PRODUCT_BOUNDARY_FIELD] == (
            TEMPLATE_PRODUCT_BOUNDARY_SOURCE_DEV_ADMIN
        )

    def test_two_builds_are_byte_identical(self, server_tree) -> None:
        first = json.dumps(tb.build_template_bundle("alpha"), sort_keys=True)
        second = json.dumps(tb.build_template_bundle("alpha"), sort_keys=True)

        assert first == second

    def test_unknown_name_raises_not_found_naming_known_templates(
        self, server_tree
    ) -> None:
        with pytest.raises(tb.TemplateNotFoundError) as exc_info:
            tb.build_template_bundle("delta")

        assert "delta" in str(exc_info.value)
        assert "alpha" in str(exc_info.value)

    @pytest.mark.parametrize("name", ["../alpha", "alpha/ops", "..", "", "  "])
    def test_non_plain_names_are_rejected(self, server_tree, name) -> None:
        with pytest.raises(tb.TemplateNotFoundError):
            tb.build_template_bundle(name)


class TestWebappTemplateProductSafety:
    def test_webapp_bundle_is_product_fetchable_without_internal_recipes(
        self,
    ) -> None:
        bundle = tb.build_template_bundle("webapp")

        assert bundle["template"] == "webapp"
        assert bundle[TEMPLATE_PRODUCT_BOUNDARY_FIELD] == (
            TEMPLATE_PRODUCT_BOUNDARY_PRODUCT
        )
        forbidden = (
            "python3 -m yoke_core",
            "uv run python -m yoke_core",
            "yoke_core",
            "db_router",
            "service_client",
            "runtime/api",
            "runtime/harness",
            "render_project",
            "bootstrap_project",
            "capability-get-secret",
            "capability-get-settings",
            "capability-list-secrets",
            "capability-set-secret",
            "capability-merge-settings",
            "render-project.sh",
            "bootstrap-project.sh",
        )
        offenders = []
        for entry in bundle["files"]:
            content = entry["content"]
            matches = [pattern for pattern in forbidden if pattern in content]
            if matches:
                offenders.append((entry["path"], matches))

        assert offenders == []
