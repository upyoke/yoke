"""Optional archive files bind both their manifest and their exact bytes."""

import hashlib
import io
import tarfile

import pytest

from yoke_core.domain import universe_archive as archive
from yoke_core.domain.universe_archive_artifacts import MANIFEST
from runtime.api.domain.test_universe_archive import _receipt_for


def _pack(tmp_path, missing_reason="artifact_source_absent", content=b"image bytes"):
    dump = tmp_path / "source.dump"
    dump.write_bytes(b"PGDMPexample")
    file = tmp_path / "screenshot.png"
    file.write_bytes(content)
    key = "qa-artifacts/example/item/1/screenshot.png"
    manifest = {
        "version": 1,
        "entries": [
            {
                "key": key,
                "status": "included",
                "original_handle": {"backend": "local", "path": str(file)},
                "project": "example",
                "artifact_id": 1,
                "bytes": file.stat().st_size,
                "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
            },
            {
                "key": "qa-artifacts/example/item/1/missing.png",
                "status": "missing",
                "original_handle": {"backend": "local", "path": "/gone/file"},
                "reason": missing_reason,
            },
        ],
    }
    target = tmp_path / "portable.tar"
    archive.pack_universe_archive(
        dump,
        _receipt_for(dump),
        target,
        artifact_manifest=manifest,
        artifact_files={key: file},
    )
    return target, key, file


@pytest.mark.parametrize(
    "reason", ["artifact_source_absent", "artifact_handle_or_owner_unavailable"]
)
def test_manifest_and_files_roundtrip(tmp_path, reason):
    target, key, file = _pack(tmp_path, reason)
    with archive.unpacked_universe_archive(target, max_dump_bytes=1 << 20) as (
        dump,
        receipt,
    ):
        assert (dump.parent / "artifacts" / key).read_bytes() == file.read_bytes()
        assert (
            hashlib.sha256((dump.parent / MANIFEST).read_bytes()).hexdigest()
            == (receipt["freeze_intent"]["archive"]["artifacts_manifest_sha256"])
        )
        archive.verify_receipt_binds_dump(receipt, dump)


@pytest.mark.parametrize("changed", [MANIFEST, "file", "extra", "traversal", "link"])
def test_tampered_or_unsafe_artifact_refuses_before_import(tmp_path, changed):
    target, key, _ = _pack(tmp_path)
    altered = tmp_path / "altered.tar"
    with tarfile.open(target) as reader, tarfile.open(altered, "w") as writer:
        for member in reader:
            data = reader.extractfile(member).read()
            if member.name == (MANIFEST if changed == MANIFEST else "artifacts/" + key):
                if changed in {MANIFEST, "file"}:
                    data = bytes([data[0] ^ 1]) + data[1:]
            member.size = len(data)
            writer.addfile(member, io.BytesIO(data))
        if changed in {"extra", "traversal", "link"}:
            name = "artifacts/shared-files/example/unlisted"
            if changed == "traversal":
                name = "artifacts/shared-files/../../escaped"
            member = tarfile.TarInfo(name)
            if changed == "link":
                member.type, member.linkname = tarfile.SYMTYPE, "/tmp/escaped"
            writer.addfile(member, io.BytesIO())
    with pytest.raises(archive.UniverseArchiveError):
        from yoke_core.domain.universe_archive_validation import inspect_archive

        inspect_archive(altered)
    assert not (tmp_path / "escaped").exists()


def test_archive_import_retains_total_artifact_cap(tmp_path):
    target, _, _ = _pack(tmp_path, content=b"x" * 100)
    with pytest.raises(archive.UniverseArchiveError, match="artifact bytes exceed the import limit"):
        with archive.unpacked_universe_archive(target, max_dump_bytes=50):
            pytest.fail("archive exceeded its artifact byte cap")


def test_archive_export_retains_packed_byte_cap(tmp_path):
    target, _, _ = _pack(tmp_path)
    destination = tmp_path / "bounded.tar"
    with archive.unpacked_universe_archive(target, max_dump_bytes=1 << 20) as (dump, receipt):
        with pytest.raises(archive.UniverseArchiveError, match="universe_export_size_limit"):
            archive.pack_universe_archive(dump, receipt, destination, max_bytes=1)
    assert not destination.exists()
