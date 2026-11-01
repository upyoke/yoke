"""Absent bytes remain explicit; unreadable bytes refuse portable exports."""

import json
import tarfile
from pathlib import Path

import pytest
from botocore.exceptions import ClientError, NoCredentialsError

from runtime.api.domain._universe_import_test_helpers import _canonical_universe
from runtime.api.domain.test_universe_artifact_transfer import Objects, _seed
from yoke_core.domain import universe_artifact_store as storage
from yoke_core.domain import universe_artifact_transfer as transfer
from yoke_core.domain import universe_export, universe_source_pause as pause
from yoke_core.domain.universe_archive import UniverseArchiveError


def _s3_error(code):
    return ClientError(
        {"Error": {"Code": code, "Message": "private details"}}, "GetObject"
    )


def _source(handle):
    return {
        "project": "example",
        "key": "qa-artifacts/example/proof",
        "original_handle": handle,
    }


@pytest.mark.parametrize(
    "error",
    [
        PermissionError("private path"),
        _s3_error("AccessDenied"),
        NoCredentialsError(),
        OSError("private host"),
    ],
)
def test_classification_refuses_without_private_error_details(error):
    with pytest.raises(UniverseArchiveError) as caught:
        transfer.classify_source_failure(_source({}), error)
    message = str(caught.value)
    assert "archive_artifact_unreadable: example qa-artifacts/example/proof:" in message
    assert "--exclude-artifacts" in message
    assert "repair access" in message
    assert "private" not in message


def test_existing_archive_refusal_is_unchanged(tmp_path, monkeypatch):
    error = UniverseArchiveError("archive_artifact_store_unavailable: configure region")
    monkeypatch.setattr(
        transfer, "artifact_sources", lambda *_a, **_k: [_source({"backend": "s3"})]
    )

    def fail(*_a, **_k):
        raise error

    monkeypatch.setattr(storage, "read_handle", fail)
    with pytest.raises(UniverseArchiveError) as caught:
        transfer.collect_artifacts(None, tmp_path, stores={})
    assert caught.value is error


@pytest.mark.parametrize("code", ["NoSuchKey", "404"])
def test_s3_absence_and_estimate_use_caller_client(tmp_path, monkeypatch, code):
    objects = Objects()
    handle = {"backend": "s3", "bucket": "evidence", "key": "gone"}

    def absent(**_kwargs):
        raise _s3_error(code)

    objects.get_object = objects.head_object = absent
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    monkeypatch.setattr(storage, "_client", lambda *_: objects)

    def factory(_project, _store):
        return objects

    with _canonical_universe() as (conn, dsn):
        _seed(conn, handle)
        manifest, files = transfer.collect_artifacts(
            conn, tmp_path, stores={}, client_factory=factory
        )
        result = transfer.estimate_universe(dsn=dsn, stores={}, client_factory=factory)
        report = universe_export.export_universe(dsn=dsn, out=tmp_path / "absent.tar")
        with tarfile.open(report["artifact"]) as archive:
            exported = json.load(archive.extractfile("artifacts-manifest.json"))
        assert exported == manifest
        assert report["artifacts"]["missing"] == 2
    assert files == {}
    assert len(manifest["entries"]) == 2
    assert all(
        e["status"] == "missing" and e["reason"] == "artifact_source_absent"
        for e in manifest["entries"]
    )
    assert result["missing_artifacts"] == 2
    assert result["artifact_bytes"] == 0
    assert result["missing_artifact_keys"] == [e["key"] for e in manifest["entries"]]


def test_estimate_refuses_access_denied(monkeypatch):
    objects = Objects()

    def denied(**_kwargs):
        raise _s3_error("AccessDenied")

    objects.head_object = denied
    with _canonical_universe() as (conn, dsn):
        _seed(conn, {"backend": "s3", "bucket": "evidence", "key": "denied"})
        with pytest.raises(
            UniverseArchiveError,
            match="archive_artifact_unreadable: yoke qa-artifacts/",
        ):
            transfer.estimate_universe(
                dsn=dsn, stores={}, client_factory=lambda *_: objects
            )


@pytest.mark.parametrize("mode", ["permission", "s3", "checkout", "oversize"])
def test_export_refuses_unreadable_or_oversized_source_and_cleans_dump(
    tmp_path, monkeypatch, mode
):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    local = tmp_path / "evidence"
    local.write_bytes(b"evidence")
    handle = {"backend": "local", "path": str(local)}
    if mode == "permission":
        real_open = Path.open

        def denied(path, *args, **kwargs):
            if path == local:
                raise PermissionError("private path")
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", denied)
    elif mode == "checkout":
        handle["path"] = "relative/evidence"
        from yoke_core.domain import project_checkout_locations

        monkeypatch.setattr(
            project_checkout_locations, "checkout_for_project_id", lambda _: None
        )
    elif mode == "oversize":
        monkeypatch.setattr(storage, "MAX_ARTIFACT_BYTES", 2)
    else:
        handle = {"backend": "s3", "bucket": "evidence", "key": "denied"}
        objects = Objects()

        def denied(**_kwargs):
            raise _s3_error("AccessDenied")

        objects.get_object = denied
        monkeypatch.setattr(storage, "_client", lambda *_: objects)
    output = tmp_path / "export.tar"
    reason = (
        "archive_artifact_too_large"
        if mode == "oversize"
        else "archive_artifact_unreadable"
    )
    with _canonical_universe() as (conn, dsn):
        _seed(conn, handle)
        with pytest.raises(universe_export.UniverseExportError) as caught:
            universe_export.export_universe(dsn=dsn, out=output)
        message = str(caught.value)
        assert reason + ": yoke qa-artifacts/" in message
        assert "--exclude-artifacts" in message
        if mode == "checkout":
            assert "attach or register" in message
        if mode == "oversize":
            assert "per-file limit" in message
        assert not output.exists()
        assert not list(tmp_path.glob(".*.dump"))
        # Explicit exclusion bypasses reads while retaining a valid DB archive.
        report = universe_export.export_universe(
            dsn=dsn, out=output, exclude_artifacts=True
        )
        assert report["artifacts"]["included"] == report["artifacts"]["missing"] == 0
        with tarfile.open(output) as archive:
            assert sorted(archive.getnames()) == [
                "freeze-receipt.json",
                "universe.dump",
            ]


def test_deleted_qa_file_exports_manifest_and_visible_missing_summary(
    tmp_path, monkeypatch, capsys
):
    from yoke_cli.commands import local_universe as cli

    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    local = tmp_path / "deleted"
    local.write_bytes(b"gone")
    local.unlink()
    lines = []
    with _canonical_universe() as (conn, dsn):
        _seed(conn, {"backend": "local", "path": str(local)})
        report = universe_export.export_universe(
            dsn=dsn, out=tmp_path / "missing.tar", emit=lines.append
        )
    with tarfile.open(report["artifact"]) as archive:
        manifest = json.load(archive.extractfile("artifacts-manifest.json"))
    entries = manifest["entries"]
    assert len(entries) == 2
    assert all(
        e["status"] == "missing" and e["reason"] == "artifact_source_absent"
        for e in entries
    )
    assert report["artifacts"]["missing"] == 2
    assert "missing artifacts: 2" in lines[-1]
    monkeypatch.setattr(cli, "resolve_https_connection", lambda: None)
    monkeypatch.setattr(cli.setup, "universe_export", lambda **_: report)
    assert cli.universe_export([]) == 0
    output = capsys.readouterr().out
    assert "missing artifacts: 2" in output
    for entry in entries:
        assert entry["key"] in lines[-1]
        assert entry["key"] in output


def test_paused_artifact_refusal_keeps_fence_and_teaches_resume(tmp_path, monkeypatch):
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
    local = tmp_path / "evidence"
    local.write_bytes(b"proof")
    real_open = Path.open

    def denied(path, *args, **kwargs):
        if path == local:
            raise PermissionError()
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied)
    with _canonical_universe() as (conn, dsn):
        _seed(conn, {"backend": "local", "path": str(local)})
        try:
            with pytest.raises(universe_export.UniverseExportError) as caught:
                universe_export.export_universe(
                    dsn=dsn, out=tmp_path / "paused.tar", pause_source=True
                )
            assert "archive_artifact_unreadable" in str(caught.value)
            assert "yoke universe resume" in str(caught.value)
            assert pause.is_paused(dsn)
            assert not (tmp_path / "paused.tar").exists()
            assert not list(tmp_path.glob(".*.dump"))
        finally:
            pause.resume(dsn)
