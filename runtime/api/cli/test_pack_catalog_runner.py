from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.cli.pack_runner_test_support import (
    make_bundle,
    make_receipt_record,
)
from yoke_cli.packs import runner
from yoke_cli.packs.catalog_source import PackCatalog
from yoke_cli.packs.errors import PackClientError
from yoke_cli.packs.receipt import load_receipt, write_receipt
from yoke_contracts.packs import PACK_RECEIPT_SCHEMA

MERGED = "b" * 40
COMMIT_CATALOG = PackCatalog(kind="commit", commit=MERGED)


def _install_fakes(monkeypatch: pytest.MonkeyPatch, fetch) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    def recording_fetch(project, pack, **kwargs):
        calls.append({"pack": pack, **kwargs})
        return fetch(pack, **kwargs)

    monkeypatch.setattr(runner, "_fetch_bundle", recording_fetch)
    monkeypatch.setattr(runner, "_assert_checkout_project", lambda *args: None)
    monkeypatch.setattr(runner, "_report_receipt", lambda *args, **kwargs: {})
    return calls


def _write_installed(
    root: Path, bundle: dict[str, object], source: dict[str, str]
) -> None:
    record = make_receipt_record(bundle)
    record["source"] = source
    write_receipt(
        root,
        {
            "schema": PACK_RECEIPT_SCHEMA,
            "project_id": 9,
            "project_slug": "sample",
            "packs": {"feature": record},
        },
    )


def test_get_from_a_merged_commit_records_that_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = make_bundle("feature", version="1.1.0", files={"feature.txt": "new\n"})
    calls = _install_fakes(monkeypatch, lambda pack, **kwargs: bundle)

    report = runner.run_pack_operation(
        tmp_path,
        project="sample",
        pack="feature",
        operation="get",
        apply=True,
        catalog=COMMIT_CATALOG,
    )

    assert report["catalog"] == {"kind": "commit", "commit": MERGED}
    assert report["plans"][0]["source"] == {"kind": "commit", "commit": MERGED}
    assert all(call["catalog"] == COMMIT_CATALOG for call in calls)
    receipt = load_receipt(tmp_path)
    assert receipt is not None
    assert receipt["packs"]["feature"]["source"] == {"kind": "commit", "commit": MERGED}


def test_served_update_refuses_a_commit_installed_version_the_release_lacks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = make_bundle("feature", version="1.1.0", files={"feature.txt": "new\n"})
    _write_installed(tmp_path, installed, {"kind": "commit", "commit": MERGED})
    (tmp_path / "feature.txt").write_text("new\n")
    served_latest = make_bundle(
        "feature", version="1.0.0", files={"feature.txt": "old\n"}
    )

    def served_fetch(pack, *, version=None, **kwargs):
        if version == "1.1.0":
            raise PackClientError(
                "pack_bundle_failed: Pack 'feature' has no version '1.1.0'"
            )
        return served_latest

    _install_fakes(monkeypatch, served_fetch)

    with pytest.raises(PackClientError) as raised:
        runner.run_pack_operation(
            tmp_path,
            project="sample",
            pack="feature",
            operation="update",
            catalog=PackCatalog(kind="served"),
        )

    message = str(raised.value)
    assert message.startswith("pack-source-unreleased:")
    assert f"--catalog commit:{MERGED}" in message


def test_served_update_adopts_a_release_that_carries_the_commit_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = make_bundle("feature", version="1.1.0", files={"feature.txt": "new\n"})
    _write_installed(tmp_path, installed, {"kind": "commit", "commit": MERGED})
    (tmp_path / "feature.txt").write_text("new\n")
    released = make_bundle("feature", version="1.2.0", files={"feature.txt": "newer\n"})

    def served_fetch(pack, *, version=None, **kwargs):
        return installed if version == "1.1.0" else released

    _install_fakes(monkeypatch, served_fetch)

    report = runner.run_pack_operation(
        tmp_path,
        project="sample",
        pack="feature",
        operation="update",
        apply=True,
        catalog=PackCatalog(kind="served"),
    )

    assert report["applied"] is True
    receipt = load_receipt(tmp_path)
    assert receipt is not None
    assert receipt["packs"]["feature"]["source"] == {"kind": "served"}
    assert receipt["packs"]["feature"]["version"] == "1.2.0"


def test_update_refuses_a_baseline_whose_content_changed_in_the_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installed = make_bundle("feature", version="1.1.0", files={"feature.txt": "new\n"})
    _write_installed(tmp_path, installed, {"kind": "lane", "commit": MERGED})
    (tmp_path / "feature.txt").write_text("new\n")
    edited = dict(installed, content_digest="e" * 64)
    _install_fakes(monkeypatch, lambda pack, **kwargs: edited)

    with pytest.raises(PackClientError, match="pack-baseline-unavailable"):
        runner.run_pack_operation(
            tmp_path,
            project="sample",
            pack="feature",
            operation="update",
            catalog=PackCatalog(kind="lane", commit="c" * 40),
        )
