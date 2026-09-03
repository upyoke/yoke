from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.cli.pack_runner_test_support import (
    make_bundle,
    make_receipt_record,
)
from yoke_cli.packs import runner
from yoke_cli.packs.receipt import load_receipt, write_receipt


def test_update_adds_new_dependency_after_handing_off_an_unchanged_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = make_bundle(
        "feature",
        version="1.0.0",
        files={"feature.txt": "old\n", "shared.txt": "shared\n"},
    )
    new = make_bundle(
        "feature",
        version="2.0.0",
        latest_version="2.0.0",
        dependencies=["foundation"],
        files={"feature.txt": "new\n"},
    )
    dependency = make_bundle("foundation", files={"shared.txt": "shared\n"})
    write_receipt(
        tmp_path,
        {
            "schema": 3,
            "project_id": 9,
            "project_slug": "sample",
            "packs": {"feature": make_receipt_record(old)},
        },
    )
    (tmp_path / "feature.txt").write_text("old\n", encoding="utf-8")
    (tmp_path / "shared.txt").write_text("shared\n", encoding="utf-8")

    def fetch(project, pack, *, version, **kwargs):
        if pack == "foundation":
            return dependency
        return old if version == "1.0.0" else new

    monkeypatch.setattr(runner, "_fetch_bundle", fetch)
    monkeypatch.setattr(runner, "_assert_checkout_project", lambda *args: None)
    monkeypatch.setattr(runner, "_report_receipt", lambda *args, **kwargs: {})

    report = runner.run_pack_operation(
        tmp_path,
        project="sample",
        pack="feature",
        operation="update",
        version="2.0.0",
        apply=True,
    )

    assert report["applied"] is True
    assert [row["pack"] for row in report["plans"]] == ["feature", "foundation"]
    assert report["plans"][0]["plan"]["retained_project_files"] == [
        {"path": "shared.txt", "reason": "removed_upstream_project_keeps_file"}
    ]
    assert report["plans"][1]["plan"]["unchanged"] == ["shared.txt"]
    assert (tmp_path / "feature.txt").read_text(encoding="utf-8") == "new\n"
    receipt = load_receipt(tmp_path)
    assert receipt is not None
    assert set(receipt["packs"]) == {"feature", "foundation"}
    assert "shared.txt" not in receipt["packs"]["feature"]["files"]
    assert "shared.txt" in receipt["packs"]["foundation"]["files"]
