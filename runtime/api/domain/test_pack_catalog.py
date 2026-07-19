from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.domain import pack_catalog


ROOT = Path(__file__).resolve().parents[3]


def test_product_catalog_covers_every_pack_with_installed_documentation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pack_catalog, "server_tree_root", lambda: ROOT)

    rows = pack_catalog.catalog_rows()

    assert {row["slug"] for row in rows} == {
        "branch-preview-hosting",
        "container-runtime",
        "domain-cdn-edge",
        "ephemeral-environments",
        "host-maintenance",
        "managed-database",
        "production-deploy",
        "pulumi-foundation",
        "registry-oidc",
        "self-hosted-runners",
        "smoke-testing",
        "structured-events",
        "vps-hosting",
        "webapp-environment-infrastructure",
        "webapp-scaffold",
    }
    for row in rows:
        assert row["documentation"].startswith("docs/packs/")
        assert row["file_count"] > 0


def test_pack_sources_are_generic_project_owned_code() -> None:
    pack_root = ROOT / "packs"
    forbidden = (
        "AUTO-GENERATED template source",
        "Do not hand-edit rendered copies",
    )

    assert not list((pack_root / "webapp-scaffold").glob("**/logo/yoke.svg"))
    for path in pack_root.rglob("*"):
        if (
            not path.is_file()
            or "__pycache__" in path.parts
            or path.suffix.lower() in {".png", ".ico", ".pyc"}
        ):
            continue
        text = path.read_text(encoding="utf-8")
        for phrase in forbidden:
            assert phrase not in text, path


def test_host_maintenance_latest_is_a_standalone_utility_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pack_catalog, "server_tree_root", lambda: ROOT)

    descriptor = pack_catalog.load_pack_descriptor("host-maintenance")
    latest = descriptor["versions"][descriptor["latest_version"]]

    assert descriptor["latest_version"] == "1.2.0"
    assert latest["dependencies"] == []
    assert latest["settings_schema"]["required"] == []
    assert {row["target"] for row in latest["files"]} == {
        "docs/packs/host-maintenance/README.md",
        "docs/packs/host-maintenance/setup.md",
        "ops/docker_image_cleanup.py",
        "ops/docker_maintenance_converge.py",
    }


def test_latest_pack_boundaries_separate_shared_and_application_specific_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pack_catalog, "server_tree_root", lambda: ROOT)

    container = pack_catalog.load_pack_descriptor("container-runtime")
    previews = pack_catalog.load_pack_descriptor("ephemeral-environments")
    preview_host = pack_catalog.load_pack_descriptor("branch-preview-hosting")
    foundation = pack_catalog.load_pack_descriptor("pulumi-foundation")
    environment = pack_catalog.load_pack_descriptor("webapp-environment-infrastructure")

    def targets(descriptor):
        latest = descriptor["versions"][descriptor["latest_version"]]
        return {row["target"] for row in latest["files"]}

    assert "ops/core-service/docker-compose.yml.tmpl" not in targets(container)
    assert "ops/ephemeral-cleanup.sh" not in targets(previews)
    assert "ops/ephemeral_cleanup.py" in targets(preview_host)
    assert "infra/webapp_environment_stack.py" not in targets(foundation)
    assert "infra/webapp_environment_stack.py" in targets(environment)


def test_bundle_records_only_used_render_values_and_preserves_github_expressions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_pack(
        tmp_path,
        files={
            "docs/packs/sample/README.md": "# Sample\n",
            ".github/workflows/{{project_name}}.yml": (
                "name: {{project_display_name}}\nrun: echo ${{ inputs.message }}\n"
            ),
            "asset.bin": b"\xff\x00",
        },
    )
    monkeypatch.setattr(pack_catalog, "server_tree_root", lambda: tmp_path)
    monkeypatch.setattr(
        pack_catalog,
        "resolve_project",
        lambda *args, **kwargs: SimpleNamespace(id=9, slug="sample"),
    )
    monkeypatch.setattr(
        pack_catalog, "_load_project_renderer_settings", lambda *args: object()
    )
    monkeypatch.setattr(
        pack_catalog,
        "gather_pulumi_values",
        lambda *args: {
            "project_name": "sample",
            "project_display_name": "Sample App",
            "unused_private_value": "must-not-leak",
        },
    )

    bundle = pack_catalog.build_pack_bundle(object(), project="sample", pack="sample")

    assert bundle["render_values"] == {
        "project_display_name": "Sample App",
        "project_name": "sample",
    }
    files = {row["path"]: row for row in bundle["files"]}
    assert files[".github/workflows/sample.yml"]["content"] == (
        "name: Sample App\nrun: echo ${{ inputs.message }}\n"
    )
    assert files["asset.bin"]["encoding"] == "base64"
    assert base64.b64decode(files["asset.bin"]["content"]) == b"\xff\x00"


def test_copy_file_remains_project_owned_runtime_template(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_pack(
        tmp_path,
        files={
            "docs/packs/sample/README.md": "# Sample\n",
            "infra/Pulumi.stack.yaml.tmpl": "name: {{runtime_name}}\n",
        },
        copy_files={"infra/Pulumi.stack.yaml.tmpl"},
    )
    monkeypatch.setattr(pack_catalog, "server_tree_root", lambda: tmp_path)
    monkeypatch.setattr(
        pack_catalog,
        "resolve_project",
        lambda *args, **kwargs: SimpleNamespace(id=9, slug="sample"),
    )
    monkeypatch.setattr(
        pack_catalog, "_load_project_renderer_settings", lambda *args: object()
    )
    monkeypatch.setattr(pack_catalog, "gather_pulumi_values", lambda *args: {})

    bundle = pack_catalog.build_pack_bundle(object(), project="sample", pack="sample")

    copied = {row["path"]: row for row in bundle["files"]}[
        "infra/Pulumi.stack.yaml.tmpl"
    ]
    assert copied["content"] == "name: {{runtime_name}}\n"
    assert bundle["render_values"] == {}


def test_old_bundle_can_be_reconstructed_from_receipt_render_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_pack(
        tmp_path,
        files={
            "docs/packs/sample/README.md": "# Sample\n",
            "config/{{project_name}}.txt": "name={{project_display_name}}\n",
        },
    )
    monkeypatch.setattr(pack_catalog, "server_tree_root", lambda: tmp_path)
    monkeypatch.setattr(
        pack_catalog,
        "resolve_project",
        lambda *args, **kwargs: SimpleNamespace(id=9, slug="renamed"),
    )
    monkeypatch.setattr(
        pack_catalog,
        "_load_project_renderer_settings",
        lambda *args: pytest.fail("live settings must not reconstruct an old baseline"),
    )

    bundle = pack_catalog.build_pack_bundle(
        object(),
        project="renamed",
        pack="sample",
        render_values={
            "project_name": "original",
            "project_display_name": "Original Name",
        },
    )

    files = {row["path"]: row for row in bundle["files"]}
    assert files["config/original.txt"]["content"] == "name=Original Name\n"


def test_descriptor_requires_documentation_inside_the_version_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_pack(tmp_path, files={"code.py": "pass\n"}, documentation="missing.md")
    monkeypatch.setattr(pack_catalog, "server_tree_root", lambda: tmp_path)

    with pytest.raises(pack_catalog.PackError, match="documentation is missing"):
        pack_catalog.load_pack_descriptor("sample")


def test_catalog_rejects_targets_shared_by_different_packs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_pack(
        tmp_path,
        slug="first",
        documentation="docs/packs/first/README.md",
        files={
            "docs/packs/first/README.md": "# First\n",
            "shared.txt": "first\n",
        },
    )
    _write_pack(
        tmp_path,
        slug="second",
        documentation="docs/packs/second/README.md",
        files={
            "docs/packs/second/README.md": "# Second\n",
            "shared.txt": "second\n",
        },
    )
    monkeypatch.setattr(pack_catalog, "server_tree_root", lambda: tmp_path)

    with pytest.raises(pack_catalog.PackError, match="overlaps target 'shared.txt'"):
        pack_catalog.list_pack_descriptors()


def test_catalog_allows_file_ownership_to_move_between_immutable_versions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_pack(
        tmp_path,
        slug="former-owner",
        files={"shared.txt": "old\n"},
        documentation="shared.txt",
    )
    former = tmp_path / "packs" / "former-owner" / "pack.json"
    descriptor = json.loads(former.read_text())
    descriptor["latest_version"] = "2.0.0"
    descriptor["versions"]["2.0.0"] = {
        "source": "versions/2.0.0/files",
        "documentation": "README.md",
        "dependencies": [],
        "settings_schema": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        "files": [
            {
                "source": "README.md",
                "target": "README.md",
                "mode": "0644",
                "render": "install",
            }
        ],
        "verification": [{"name": "check", "command": "git diff --check"}],
    }
    latest_root = tmp_path / "packs" / "former-owner" / "versions" / "2.0.0" / "files"
    latest_root.mkdir(parents=True)
    (latest_root / "README.md").write_text("Former owner\n")
    former.write_text(json.dumps(descriptor))
    _write_pack(
        tmp_path,
        slug="new-owner",
        files={"shared.txt": "new\n"},
        documentation="shared.txt",
    )
    monkeypatch.setattr(pack_catalog, "server_tree_root", lambda: tmp_path)

    assert {row["slug"] for row in pack_catalog.list_pack_descriptors()} == {
        "former-owner",
        "new-owner",
    }


def _write_pack(
    root: Path,
    *,
    slug: str = "sample",
    files: dict[str, str | bytes],
    documentation: str = "docs/packs/sample/README.md",
    copy_files: set[str] | None = None,
) -> Path:
    pack = root / "packs" / slug
    source = pack / "versions" / "1.0.0" / "files"
    source.mkdir(parents=True)
    for rel, content in files.items():
        path = source / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    copied = copy_files or set()
    placeholders: set[str] = set()
    file_records: list[dict[str, str]] = []
    for rel, content in sorted(files.items()):
        render = "copy" if rel in copied else "install"
        target = (
            rel if render == "copy" else (rel[:-5] if rel.endswith(".tmpl") else rel)
        )
        file_records.append(
            {"source": rel, "target": target, "mode": "0644", "render": render}
        )
        if render == "install" and isinstance(content, str):
            placeholders.update(pack_catalog._PLACEHOLDER.findall(target))
            placeholders.update(pack_catalog._PLACEHOLDER.findall(content))
    (pack / "pack.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "slug": slug,
                "name": slug.title(),
                "description": f"{slug.title()} Pack.",
                "latest_version": "1.0.0",
                "versions": {
                    "1.0.0": {
                        "source": "versions/1.0.0/files",
                        "documentation": documentation,
                        "dependencies": [],
                        "settings_schema": {
                            "type": "object",
                            "properties": {
                                key: {
                                    "type": "string",
                                    "description": f"Value for {key}.",
                                }
                                for key in sorted(placeholders)
                            },
                            "required": sorted(placeholders),
                            "additionalProperties": False,
                        },
                        "files": file_records,
                        "verification": [
                            {"name": "source-check", "command": "git diff --check"}
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return source
