from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from yoke_cli.packs import remove
from yoke_cli.packs.receipt import load_receipt, write_receipt
from yoke_contracts.packs import PACK_RECEIPT_REL, PACK_RECEIPT_SCHEMA


def _digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _record(path: str, version: str = "1.0.0") -> dict:
    digest = _digest(path)
    return {
        "version": version,
        "content_digest": digest,
        "render_values": {},
        "prerequisites": [],
        "source": {"kind": "served"},
        "files": {path: {"path": path, "sha256": digest, "mode": 0o644}},
    }


def _write_project(root: Path) -> None:
    write_receipt(
        root,
        {
            "schema": PACK_RECEIPT_SCHEMA,
            "project_id": 9,
            "project_slug": "sample",
            "packs": {
                "base": _record("base.txt"),
                "app": _record("app.txt", "2.0.0"),
                "extra": _record("extra.txt"),
            },
        },
    )
    for name in ("base.txt", "app.txt", "extra.txt"):
        (root / name).write_text(name)


def _fakes(monkeypatch, *, dependencies=None, unreadable=(), reports=None):
    dependencies = dependencies or {"app": ["base"]}
    fetched: list[tuple[str, str]] = []

    def fetch(project, slug, *, version, render_values, session_id, catalog):
        fetched.append((slug, version))
        if slug in unreadable:
            raise remove.PackClientError(f"pack_bundle_failed: {slug} is gone")
        return {"pack": slug, "dependencies": dependencies.get(slug, [])}

    def report(project, receipt, *, session_id):
        if reports is not None:
            reports.append(sorted(receipt["packs"]))
        return {"reported": len(receipt["packs"])}

    monkeypatch.setattr(remove, "_fetch_bundle", fetch)
    monkeypatch.setattr(remove, "_report_receipt", report)
    monkeypatch.setattr(remove, "_assert_checkout_receipt", lambda *args: None)
    return fetched


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_preview_names_drops_and_kept_files_without_writing(tmp_path, monkeypatch):
    _write_project(tmp_path)
    reports: list = []
    _fakes(monkeypatch, reports=reports)
    before = _snapshot(tmp_path)

    report = remove.run_pack_remove(tmp_path, project="sample", pack="app")

    assert report["applied"] is False
    assert report["kept_project_files"] == ["app.txt"]
    assert report["remaining_packs"] == ["base", "extra"]
    assert any("server install record" in row for row in report["drops"])
    assert _snapshot(tmp_path) == before
    assert reports == []


def test_apply_drops_only_the_pack_record_and_keeps_every_file(tmp_path, monkeypatch):
    _write_project(tmp_path)
    reports: list = []
    _fakes(monkeypatch, reports=reports)
    before = _snapshot(tmp_path)
    original = load_receipt(tmp_path)

    report = remove.run_pack_remove(tmp_path, project="sample", pack="app", apply=True)

    assert report["applied"] is True
    assert reports == [["base", "extra"]]
    after = _snapshot(tmp_path)
    assert {k for k in after if after[k] != before.get(k)} == {PACK_RECEIPT_REL}
    assert set(after) == set(before)
    receipt = load_receipt(tmp_path)
    del original["packs"]["app"]
    assert receipt == original


def test_refuses_to_remove_a_dependency_of_an_installed_pack(tmp_path, monkeypatch):
    _write_project(tmp_path)
    _fakes(monkeypatch)
    before = _snapshot(tmp_path)

    with pytest.raises(remove.PackClientError, match="pack-required-by-installed.*'app'"):
        remove.run_pack_remove(tmp_path, project="sample", pack="base", apply=True)

    assert _snapshot(tmp_path) == before


def test_dependencies_are_read_at_each_other_pack_recorded_version(
    tmp_path, monkeypatch
):
    _write_project(tmp_path)
    fetched = _fakes(monkeypatch)

    remove.run_pack_remove(tmp_path, project="sample", pack="extra")

    assert sorted(fetched) == [("app", "2.0.0"), ("base", "1.0.0")]


def test_refuses_when_another_pack_version_cannot_be_read(tmp_path, monkeypatch):
    _write_project(tmp_path)
    _fakes(monkeypatch, unreadable={"extra"})

    with pytest.raises(
        remove.PackClientError, match="pack-dependencies-unknown: installed Pack 'extra'"
    ):
        remove.run_pack_remove(tmp_path, project="sample", pack="app", apply=True)

    assert "app" in load_receipt(tmp_path)["packs"]


def test_removes_a_pack_that_left_the_catalog(tmp_path, monkeypatch):
    _write_project(tmp_path)
    fetched = _fakes(monkeypatch, unreadable={"app"})

    report = remove.run_pack_remove(tmp_path, project="sample", pack="app", apply=True)

    assert report["applied"] is True
    assert "app" not in {slug for slug, _ in fetched}
    assert "app" not in load_receipt(tmp_path)["packs"]


@pytest.mark.parametrize("pack", ["never-installed", "app"])
def test_refuses_a_pack_that_is_not_installed(tmp_path, monkeypatch, pack):
    _write_project(tmp_path)
    _fakes(monkeypatch)
    if pack == "app":
        remove.run_pack_remove(tmp_path, project="sample", pack="app", apply=True)

    with pytest.raises(remove.PackClientError, match="pack-not-installed"):
        remove.run_pack_remove(tmp_path, project="sample", pack=pack, apply=True)


def test_refuses_without_a_receipt(tmp_path, monkeypatch):
    _fakes(monkeypatch)
    with pytest.raises(remove.PackClientError, match="pack-not-installed"):
        remove.run_pack_remove(tmp_path, project="sample", pack="app")


def test_failed_server_report_leaves_the_receipt_unchanged(tmp_path, monkeypatch):
    _write_project(tmp_path)
    _fakes(monkeypatch)

    def failing(*args, **kwargs):
        raise remove.PackClientError("pack_report_failed: offline")

    monkeypatch.setattr(remove, "_report_receipt", failing)
    before = _snapshot(tmp_path)

    with pytest.raises(remove.PackClientError, match="offline"):
        remove.run_pack_remove(tmp_path, project="sample", pack="app", apply=True)

    assert _snapshot(tmp_path) == before


def test_refuses_a_project_that_does_not_own_the_receipt(tmp_path, monkeypatch):
    _write_project(tmp_path)
    _fakes(monkeypatch)
    monkeypatch.undo()
    with pytest.raises(remove.PackClientError, match="pack-project-mismatch"):
        remove.run_pack_remove(tmp_path, project="other", pack="app")


def test_invalid_receipt_refuses_with_a_named_reason(tmp_path):
    (tmp_path / ".yoke").mkdir()
    (tmp_path / PACK_RECEIPT_REL).write_text(json.dumps({"schema": 99}))
    with pytest.raises(remove.PackClientError, match="pack-receipt-invalid"):
        remove.run_pack_remove(tmp_path, project="sample", pack="app")
