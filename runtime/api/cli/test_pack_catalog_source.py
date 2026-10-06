from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from runtime.api.domain.pack_catalog_test_support import write_pack
from yoke_cli.packs.catalog_baseline import overlay_catalog_rows
from yoke_cli.packs.catalog_source import PackCatalog, resolve_catalog
from yoke_cli.packs.errors import PackClientError
from yoke_cli.packs.runner_support import _validate_bundle
from yoke_contracts.install_binding import SOURCE_DEV_RUN_ROOT_ENV
from yoke_core.domain import pack_catalog
from yoke_core.domain.pack_catalog import PackError
from yoke_core.domain.pack_submitted_source import render_submitted_pack_bundle


@pytest.fixture(autouse=True)
def _outside_source_dev_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SOURCE_DEV_RUN_ROOT_ENV, raising=False)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _yoke_checkout(root: Path) -> Path:
    """A minimal Yoke-shaped clone whose origin default branch is ``main``."""
    (root / "runtime" / "harness").mkdir(parents=True)
    (root / "runtime" / "harness" / "README.md").write_text("harness\n")
    (root / "pyproject.toml").write_text('[project]\nname = "yoke"\n')
    write_pack(root, files={"docs/packs/sample/README.md": "# Sample\n"})
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "-c", "user.email=t@e", "-c", "user.name=t", "commit", "-qm", "base")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(root, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
    return root


def _add_version(root: Path, version: str, content: str) -> None:
    descriptor_path = root / "packs" / "sample" / "pack.json"
    descriptor = json.loads(descriptor_path.read_text())
    record = json.loads(json.dumps(descriptor["versions"]["1.0.0"]))
    record["source"] = f"versions/{version}/files"
    record["files"].append(
        {"source": "notes.txt", "target": "notes.txt", "mode": "0644", "render": "copy"}
    )
    source = root / "packs" / "sample" / "versions" / version / "files"
    (source / "docs" / "packs" / "sample").mkdir(parents=True)
    (source / "docs" / "packs" / "sample" / "README.md").write_text("# Sample\n")
    (source / "notes.txt").write_text(content)
    descriptor["versions"][version] = record
    descriptor["latest_version"] = version
    descriptor_path.write_text(json.dumps(descriptor))


def test_omitted_catalog_is_served_outside_source_dev_run() -> None:
    assert resolve_catalog(None) == PackCatalog(kind="served")


def test_lane_catalog_submits_the_whole_pack_source_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = _yoke_checkout(tmp_path)
    _add_version(checkout, "1.1.0", "lane notes\n")
    monkeypatch.setenv(SOURCE_DEV_RUN_ROOT_ENV, str(checkout))

    catalog = resolve_catalog(None)
    files = {row["path"]: row["content"] for row in catalog.pack_files("sample")}

    assert catalog.kind == "lane"
    assert catalog.source() == {
        "kind": "lane",
        "commit": _git(checkout, "rev-parse", "HEAD"),
    }
    assert set(files) == {
        "sample/pack.json",
        "sample/versions/1.0.0/files/docs/packs/sample/README.md",
        "sample/versions/1.1.0/files/docs/packs/sample/README.md",
        "sample/versions/1.1.0/files/notes.txt",
    }
    assert (
        base64.b64decode(files["sample/versions/1.1.0/files/notes.txt"])
        == b"lane notes\n"
    )
    assert catalog.descriptors()["sample"]["latest_version"] == "1.1.0"


def test_commit_catalog_reads_a_merged_commit_not_the_working_tree(
    tmp_path: Path,
) -> None:
    checkout = _yoke_checkout(tmp_path)
    _add_version(checkout, "1.1.0", "merged notes\n")
    _git(checkout, "add", "-A")
    _git(checkout, "-c", "user.email=t@e", "-c", "user.name=t", "commit", "-qm", "v1.1")
    _git(checkout, "update-ref", "refs/remotes/origin/main", "HEAD")
    merged = _git(checkout, "rev-parse", "HEAD")
    (
        checkout / "packs" / "sample" / "versions" / "1.1.0" / "files" / "notes.txt"
    ).write_text("uncommitted\n")

    catalog = resolve_catalog(f"commit:{merged[:12]}", yoke_checkout=str(checkout))
    files = {row["path"]: row["content"] for row in catalog.pack_files("sample")}

    assert catalog.source() == {"kind": "commit", "commit": merged}
    assert (
        base64.b64decode(files["sample/versions/1.1.0/files/notes.txt"])
        == b"merged notes\n"
    )
    assert set(catalog.descriptors()) == {"sample"}


def test_commit_catalog_refuses_a_commit_not_merged_into_the_default_branch(
    tmp_path: Path,
) -> None:
    checkout = _yoke_checkout(tmp_path)
    _add_version(checkout, "1.1.0", "unmerged\n")
    _git(checkout, "add", "-A")
    _git(checkout, "-c", "user.email=t@e", "-c", "user.name=t", "commit", "-qm", "wip")
    unmerged = _git(checkout, "rev-parse", "HEAD")

    with pytest.raises(PackClientError, match="pack-catalog-commit-unmerged"):
        resolve_catalog(f"commit:{unmerged}", yoke_checkout=str(checkout))


def test_commit_catalog_requires_a_yoke_source_checkout(tmp_path: Path) -> None:
    with pytest.raises(PackClientError, match="pack-catalog-checkout-missing"):
        resolve_catalog("commit:abc", yoke_checkout=str(tmp_path))


def test_catalog_names_a_pack_it_does_not_carry(tmp_path: Path) -> None:
    catalog = PackCatalog(
        kind="lane", checkout=_yoke_checkout(tmp_path), commit="c" * 40
    )

    with pytest.raises(PackClientError, match="pack-catalog-missing-pack"):
        catalog.pack_files("absent")


def test_unknown_catalog_names_the_accepted_values() -> None:
    with pytest.raises(PackClientError, match="served, lane, or commit:SHA"):
        resolve_catalog("release")


def test_server_renders_submitted_lane_source_into_a_valid_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout = _yoke_checkout(tmp_path)
    _add_version(checkout, "1.1.0", "lane notes\n")
    monkeypatch.setenv(SOURCE_DEV_RUN_ROOT_ENV, str(checkout))
    catalog = resolve_catalog("lane")
    monkeypatch.setattr(
        pack_catalog,
        "resolve_project",
        lambda *args, **kwargs: SimpleNamespace(id=9, slug="sample"),
    )

    bundle = render_submitted_pack_bundle(
        object(),
        project="sample",
        pack="sample",
        source=catalog.source(),
        files=catalog.pack_files("sample"),
        render_values={},
    )

    _validate_bundle(bundle)
    assert bundle["version"] == "1.1.0"
    assert bundle["catalog"] == catalog.source()
    assert {row["path"] for row in bundle["files"]} == {
        "docs/packs/sample/README.md",
        "notes.txt",
    }


def test_server_refuses_submitted_source_outside_the_named_pack() -> None:
    escaping = [
        {"path": "sample/pack.json", "content": ""},
        {"path": "other/pack.json", "content": ""},
    ]

    with pytest.raises(PackError, match="outside Pack 'sample'"):
        render_submitted_pack_bundle(
            object(),
            project="sample",
            pack="sample",
            source={"kind": "commit", "commit": "a" * 40},
            files=escaping,
        )


def test_server_refuses_a_submission_claiming_the_served_catalog() -> None:
    with pytest.raises(PackError, match="cannot claim the served catalog"):
        render_submitted_pack_bundle(
            object(),
            project="sample",
            pack="sample",
            source={"kind": "served"},
            files=[],
        )


def test_lane_listing_restates_status_against_lane_versions() -> None:
    served = [
        {
            "slug": "sample",
            "status": "installed",
            "installed_version": "1.0.0",
            "latest_version": "1.0.0",
            "stale_reasons": [],
        }
    ]
    descriptors = {
        "sample": {"latest_version": "1.1.0", "versions": {"1.1.0": {"files": []}}},
        "fresh": {"latest_version": "0.1.0", "versions": {"0.1.0": {"files": []}}},
    }

    rows = {row["slug"]: row for row in overlay_catalog_rows(served, descriptors)}

    assert rows["sample"]["status"] == "stale"
    assert rows["sample"]["stale_reasons"] == ["update_available"]
    assert rows["sample"]["latest_version"] == "1.1.0"
    assert rows["fresh"]["status"] == "available"
    assert rows["fresh"]["in_catalog"] is True
