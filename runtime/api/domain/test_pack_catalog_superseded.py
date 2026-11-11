"""A Pack version may name the newer version that supersedes it."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

from yoke_cli.commands.adapters import packs as packs_adapter
from yoke_cli.packs.catalog_source import PackCatalog
from yoke_core.domain import pack_catalog
from runtime.api.domain.pack_catalog_test_support import write_pack


def _two_versions(root: Path, **old_fields) -> Path:
    write_pack(root, files={"docs/packs/sample/README.md": "# Sample\n"})
    pack = root / "packs" / "sample"
    shutil.copytree(pack / "versions/1.0.0", pack / "versions/2.0.0")
    descriptor = json.loads((pack / "pack.json").read_text())
    newer = dict(descriptor["versions"]["1.0.0"], source="versions/2.0.0/files")
    descriptor["versions"]["2.0.0"] = newer
    descriptor["latest_version"] = "2.0.0"
    descriptor["versions"]["1.0.0"].update(old_fields)
    (pack / "pack.json").write_text(json.dumps(descriptor))
    return pack


def test_superseded_version_still_bundles_and_names_its_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _two_versions(tmp_path, superseded_by="2.0.0")
    monkeypatch.setattr(pack_catalog, "server_tree_root", lambda: tmp_path)
    monkeypatch.setattr(
        pack_catalog,
        "resolve_project",
        lambda *args, **kwargs: SimpleNamespace(id=9, slug="sample"),
    )

    old = pack_catalog.build_pack_bundle(
        object(), project="sample", pack="sample", version="1.0.0", render_values={}
    )
    latest = pack_catalog.build_pack_bundle(
        object(), project="sample", pack="sample", render_values={}
    )

    assert (old["version"], old["superseded_by"]) == ("1.0.0", "2.0.0")
    assert (latest["version"], latest["superseded_by"]) == ("2.0.0", "")


@pytest.mark.parametrize(
    ("fields", "latest_fields"),
    [
        ({"superseded_by": "3.0.0"}, {}),
        ({"superseded_by": "1.0.0"}, {}),
        ({"superseded_by": 2}, {}),
        ({"superseded_by": "2.0.0"}, {"superseded_by": "1.0.0"}),
    ],
    ids=["unknown", "not-newer", "not-a-string", "latest-superseded"],
)
def test_superseded_by_must_name_a_newer_current_version(
    tmp_path: Path, fields: dict, latest_fields: dict
) -> None:
    pack = _two_versions(tmp_path, **fields)
    descriptor = json.loads((pack / "pack.json").read_text())
    descriptor["versions"]["2.0.0"].update(latest_fields)
    (pack / "pack.json").write_text(json.dumps(descriptor))

    with pytest.raises(pack_catalog.PackError, match="superseded_by"):
        pack_catalog.load_pack_descriptor("sample", tmp_path / "packs")


def _run_get(monkeypatch, catalog: PackCatalog, version: str | None, capsys):
    reports: list[dict] = []

    def _operation(*_args, **kwargs):
        reports.append({"operation": "get", "version": kwargs["version"]})
        return reports[-1]

    monkeypatch.setattr(packs_adapter, "resolve_catalog", lambda *a, **k: catalog)
    monkeypatch.setattr(packs_adapter, "run_pack_operation", _operation)
    args = ["sample", "--project", "acme", "--json"]
    code = packs_adapter.packs_get(args + (["--version", version] if version else []))
    captured = capsys.readouterr()
    return code, json.loads(captured.out), captured.err


def test_explicit_superseded_version_installs_with_a_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    _two_versions(tmp_path, superseded_by="2.0.0")
    catalog = PackCatalog(kind="lane", checkout=tmp_path, commit="abc")

    code, report, err = _run_get(monkeypatch, catalog, "1.0.0", capsys)

    assert code == 0
    assert report["version"] == "1.0.0"
    assert "superseded by '2.0.0'" in err
    assert "--version 2.0.0" in err
    assert report["warnings"] == [err.strip().removeprefix("warning: ")]


def test_served_catalog_reads_supersession_from_the_bundle(
    monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(
        packs_adapter, "_fetch_bundle", lambda *a, **k: {"superseded_by": "2.0.0"}
    )

    code, report, err = _run_get(
        monkeypatch, PackCatalog(kind="served"), "1.0.0", capsys
    )

    assert code == 0
    assert "superseded by '2.0.0'" in err


def test_unpinned_or_current_versions_print_no_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    _two_versions(tmp_path, superseded_by="2.0.0")
    catalog = PackCatalog(kind="lane", checkout=tmp_path, commit="abc")

    for version in (None, "2.0.0"):
        code, report, err = _run_get(monkeypatch, catalog, version, capsys)
        assert (code, err, "warnings" in report) == (0, "", False)
