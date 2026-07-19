from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from yoke_cli.packs import runner
from yoke_cli.packs.receipt import load_receipt, write_receipt


def test_get_applies_dependencies_then_selected_pack_and_reports_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dependency = _bundle("foundation", files={"foundation.txt": "foundation\n"})
    selected = _bundle(
        "feature",
        dependencies=["foundation"],
        files={"feature.txt": "feature\n"},
    )
    bundles = {"foundation": dependency, "feature": selected}
    monkeypatch.setattr(
        runner,
        "_fetch_bundle",
        lambda project, pack, **kwargs: bundles[pack],
    )
    monkeypatch.setattr(runner, "_assert_checkout_project", lambda *args: None)
    reported: list[dict[str, object]] = []
    monkeypatch.setattr(
        runner,
        "_report_receipt",
        lambda project, receipt, **kwargs: reported.append(receipt) or {"reported": 2},
    )

    report = runner.run_pack_operation(
        tmp_path,
        project="sample",
        pack="feature",
        operation="get",
        apply=True,
    )

    assert report["applied"] is True
    assert [row["pack"] for row in report["plans"]] == ["foundation", "feature"]
    assert (tmp_path / "foundation.txt").read_text(encoding="utf-8") == "foundation\n"
    assert (tmp_path / "feature.txt").read_text(encoding="utf-8") == "feature\n"
    receipt = load_receipt(tmp_path)
    assert receipt is not None
    assert set(receipt["packs"]) == {"foundation", "feature"}
    assert reported == [receipt]


def test_update_reconstructs_old_version_with_recorded_render_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = _bundle(
        "feature",
        version="1.0.0",
        render_values={"project_display_name": "Old Name"},
        files={"feature.txt": "name=Old Name\nkeep=one\nkeep=two\nlocal=base\n"},
    )
    new = _bundle(
        "feature",
        version="2.0.0",
        latest_version="2.0.0",
        render_values={"project_display_name": "New Name"},
        files={"feature.txt": "name=New Name\nkeep=one\nkeep=two\nlocal=base\n"},
    )
    receipt = {
        "schema": 2,
        "project_id": 9,
        "project_slug": "sample",
        "packs": {"feature": _receipt_record(old)},
    }
    write_receipt(tmp_path, receipt)
    (tmp_path / "feature.txt").write_text(
        "name=Old Name\nkeep=one\nkeep=two\nlocal=custom\n", encoding="utf-8"
    )
    calls: list[tuple[str | None, dict[str, str] | None]] = []

    def fetch(project, pack, *, version, render_values=None, **kwargs):
        calls.append((version, render_values))
        return old if version == "1.0.0" else new

    monkeypatch.setattr(runner, "_fetch_bundle", fetch)
    monkeypatch.setattr(runner, "_assert_checkout_project", lambda *args: None)
    monkeypatch.setattr(runner, "_report_receipt", lambda *args, **kwargs: {})

    report = runner.run_pack_operation(
        tmp_path,
        project="sample",
        pack="feature",
        operation="update",
        apply=True,
        version="2.0.0",
    )

    assert report["applied"] is True
    assert calls == [
        ("2.0.0", None),
        ("1.0.0", {"project_display_name": "Old Name"}),
    ]
    assert (tmp_path / "feature.txt").read_text(encoding="utf-8") == (
        "name=New Name\nkeep=one\nkeep=two\nlocal=custom\n"
    )


def test_conflicted_update_refuses_all_writes(tmp_path: Path, monkeypatch) -> None:
    old = _bundle("feature", version="1.0.0", files={"feature.txt": "value=old\n"})
    new = _bundle(
        "feature",
        version="2.0.0",
        latest_version="2.0.0",
        files={"feature.txt": "value=new\n", "created.txt": "new\n"},
    )
    write_receipt(
        tmp_path,
        {
            "schema": 2,
            "project_id": 9,
            "project_slug": "sample",
            "packs": {"feature": _receipt_record(old)},
        },
    )
    (tmp_path / "feature.txt").write_text("value=custom\n", encoding="utf-8")
    monkeypatch.setattr(
        runner,
        "_fetch_bundle",
        lambda project, pack, *, version, **kwargs: old if version == "1.0.0" else new,
    )
    monkeypatch.setattr(runner, "_assert_checkout_project", lambda *args: None)

    report = runner.run_pack_operation(
        tmp_path,
        project="sample",
        pack="feature",
        operation="update",
        apply=True,
        version="2.0.0",
    )

    assert report["refused"] is True
    assert report["conflict_count"] == 1
    assert not (tmp_path / "created.txt").exists()
    assert load_receipt(tmp_path)["packs"]["feature"]["version"] == "1.0.0"


def test_update_can_accept_an_exact_manually_resolved_current_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = _bundle("feature", version="1.0.0", files={"feature.txt": "value=old\n"})
    new = _bundle(
        "feature",
        version="2.0.0",
        latest_version="2.0.0",
        files={"feature.txt": "value=new\n", "created.txt": "new\n"},
    )
    write_receipt(
        tmp_path,
        {
            "schema": 2,
            "project_id": 9,
            "project_slug": "sample",
            "packs": {"feature": _receipt_record(old)},
        },
    )
    resolved = "value=custom-with-new-behavior\n"
    (tmp_path / "feature.txt").write_text(resolved, encoding="utf-8")
    monkeypatch.setattr(
        runner,
        "_fetch_bundle",
        lambda project, pack, *, version, **kwargs: old if version == "1.0.0" else new,
    )
    monkeypatch.setattr(runner, "_assert_checkout_project", lambda *args: None)
    monkeypatch.setattr(runner, "_report_receipt", lambda *args, **kwargs: {})

    report = runner.run_pack_operation(
        tmp_path,
        project="sample",
        pack="feature",
        operation="update",
        apply=True,
        version="2.0.0",
        accepted_current_paths=["feature.txt"],
    )

    assert report["applied"] is True
    assert report["conflict_count"] == 0
    assert report["plans"][0]["plan"]["accepted_current"] == [
        {
            "path": "feature.txt",
            "reason": "overlapping_customization",
            "content_conflict": True,
            "mode_conflict": False,
        }
    ]
    assert (tmp_path / "feature.txt").read_text(encoding="utf-8") == resolved
    assert (tmp_path / "created.txt").read_text(encoding="utf-8") == "new\n"
    assert load_receipt(tmp_path)["packs"]["feature"]["version"] == "2.0.0"


def test_update_rejects_accept_current_for_a_nonconflicting_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = _bundle("feature", version="1.0.0", files={"feature.txt": "value=old\n"})
    new = _bundle(
        "feature",
        version="2.0.0",
        latest_version="2.0.0",
        files={"feature.txt": "value=new\n"},
    )
    write_receipt(
        tmp_path,
        {
            "schema": 2,
            "project_id": 9,
            "project_slug": "sample",
            "packs": {"feature": _receipt_record(old)},
        },
    )
    (tmp_path / "feature.txt").write_text("value=custom\n", encoding="utf-8")
    monkeypatch.setattr(
        runner,
        "_fetch_bundle",
        lambda project, pack, *, version, **kwargs: old if version == "1.0.0" else new,
    )
    monkeypatch.setattr(runner, "_assert_checkout_project", lambda *args: None)

    with pytest.raises(
        runner.PackClientError,
        match="not an unresolved Pack conflict: typo.txt",
    ):
        runner.run_pack_operation(
            tmp_path,
            project="sample",
            pack="feature",
            operation="update",
            accepted_current_paths=["typo.txt"],
        )


def test_projection_failure_does_not_undo_successful_local_apply(
    tmp_path: Path,
    monkeypatch,
) -> None:
    selected = _bundle("feature", files={"feature.txt": "feature\n"})
    monkeypatch.setattr(runner, "_fetch_bundle", lambda *args, **kwargs: selected)
    monkeypatch.setattr(runner, "_assert_checkout_project", lambda *args: None)
    monkeypatch.setattr(
        runner,
        "_report_receipt",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            runner.PackClientError("report service unavailable")
        ),
    )

    report = runner.run_pack_operation(
        tmp_path,
        project="sample",
        pack="feature",
        operation="get",
        apply=True,
    )

    assert report["applied"] is True
    assert report["projection"] is None
    assert report["projection_warning"] == "report service unavailable"
    assert (tmp_path / "feature.txt").is_file()
    assert load_receipt(tmp_path) is not None


def test_update_follows_the_project_path_recorded_by_relink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = _bundle("feature", version="1.0.0", files={"feature.txt": "old\n"})
    new = _bundle(
        "feature",
        version="2.0.0",
        latest_version="2.0.0",
        files={"feature.txt": "new\n"},
    )
    record = _receipt_record(old)
    record["files"]["feature.txt"]["path"] = "src/moved-feature.txt"
    write_receipt(
        tmp_path,
        {
            "schema": 2,
            "project_id": 9,
            "project_slug": "sample",
            "packs": {"feature": record},
        },
    )
    destination = tmp_path / "src" / "moved-feature.txt"
    destination.parent.mkdir()
    destination.write_text("old\n", encoding="utf-8")
    monkeypatch.setattr(
        runner,
        "_fetch_bundle",
        lambda project, pack, *, version, **kwargs: old if version == "1.0.0" else new,
    )
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
    assert destination.read_text(encoding="utf-8") == "new\n"
    assert not (tmp_path / "feature.txt").exists()
    assert (
        load_receipt(tmp_path)["packs"]["feature"]["files"]["feature.txt"]["path"]
        == "src/moved-feature.txt"
    )


def _bundle(
    slug: str,
    *,
    version: str = "1.0.0",
    latest_version: str | None = None,
    dependencies: list[str] | None = None,
    render_values: dict[str, str] | None = None,
    files: dict[str, str],
) -> dict[str, object]:
    entries = []
    for path, content in files.items():
        entries.append(
            {
                "path": path,
                "content": content,
                "encoding": "utf-8",
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "mode": 0o644,
            }
        )
    content_digest = hashlib.sha256(
        slug.encode("utf-8") + version.encode("utf-8")
    ).hexdigest()
    return {
        "bundle_schema": 1,
        "project_id": 9,
        "project_slug": "sample",
        "pack": slug,
        "name": slug.title(),
        "description": f"{slug} Pack.",
        "version": version,
        "latest_version": latest_version or version,
        "dependencies": dependencies or [],
        "render_values": render_values or {},
        "files": entries,
        "content_digest": content_digest,
    }


def _receipt_record(bundle: dict[str, object]) -> dict[str, object]:
    files = bundle["files"]
    assert isinstance(files, list)
    return {
        "version": bundle["version"],
        "content_digest": bundle["content_digest"],
        "render_values": bundle["render_values"],
        "files": {
            row["path"]: {
                "path": row["path"],
                "sha256": row["sha256"],
                "mode": row["mode"],
            }
            for row in files
        },
    }
