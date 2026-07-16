"""Safety and binding tests for the one-file portable universe archive."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest

from yoke_core.domain import universe_archive as ua
from yoke_core.domain.json_helper import dumps_pretty
from yoke_core.domain.source_freeze_intent import file_sha256


def _receipt_for(dump: Path) -> dict:
    return {
        "freeze_intent": {
            "schema": "yoke.source-freeze/v1",
            "database": {"name": "yoke", "oid": 7, "org": "default"},
            "archive": {
                "sha256": file_sha256(dump),
                "bytes": dump.stat().st_size,
                "catalog_digest": "d" * 64,
            },
        },
        "source_authority": {"receipt_digest": "stable"},
    }


def _packed(tmp_path: Path, payload: bytes = b"PGDMPpayload") -> Path:
    dump = tmp_path / "staged.dump"
    dump.write_bytes(payload)
    destination = tmp_path / "org-universe.tar"
    ua.pack_universe_archive(dump, _receipt_for(dump), destination)
    return destination


def _hand_rolled(tmp_path: Path, members: dict[str, bytes]) -> Path:
    archive = tmp_path / "hand-rolled.tar"
    with tarfile.open(archive, mode="w") as writer:
        for name, body in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(body)
            writer.addfile(info, io.BytesIO(body))
    return archive


def test_pack_then_unpack_round_trips_both_members(tmp_path):
    artifact = _packed(tmp_path)
    with tarfile.open(artifact, mode="r:") as reader:
        names = [member.name for member in reader.getmembers()]
    # Receipt first: streaming readers verify intent before the payload.
    assert names == [ua.ARCHIVE_MEMBER_RECEIPT, ua.ARCHIVE_MEMBER_DUMP]

    work = tmp_path / "unpacked"
    work.mkdir()
    dump, receipt = ua.unpack_universe_archive(
        artifact, work, max_dump_bytes=1 << 20,
    )
    assert dump.read_bytes() == b"PGDMPpayload"
    binding = ua.verify_receipt_binds_dump(receipt, dump)
    assert binding == {
        "sha256": file_sha256(dump),
        "bytes": dump.stat().st_size,
    }


def test_pack_failure_leaves_no_artifact(tmp_path):
    dump = tmp_path / "staged.dump"
    dump.write_bytes(b"PGDMP")
    destination = tmp_path / "protected" / "org-universe.tar"
    destination.parent.mkdir()
    protected = tmp_path / "elsewhere.tar"
    protected.write_bytes(b"must remain")
    destination.symlink_to(protected)

    with pytest.raises(ua.UniverseArchiveError, match="single-link regular"):
        ua.pack_universe_archive(dump, _receipt_for(dump), destination)

    assert protected.read_bytes() == b"must remain"
    assert [entry.name for entry in destination.parent.iterdir()] == [
        destination.name
    ]


def test_unpack_refuses_unexpected_member(tmp_path):
    dump_body = b"PGDMPpayload"
    archive = _hand_rolled(
        tmp_path,
        {
            ua.ARCHIVE_MEMBER_RECEIPT: b"{}",
            ua.ARCHIVE_MEMBER_DUMP: dump_body,
            "extra.txt": b"nope",
        },
    )
    with pytest.raises(ua.UniverseArchiveError, match="unexpected member"):
        ua.unpack_universe_archive(archive, tmp_path, max_dump_bytes=1 << 20)


def test_unpack_refuses_missing_receipt(tmp_path):
    archive = _hand_rolled(tmp_path, {ua.ARCHIVE_MEMBER_DUMP: b"PGDMP"})
    with pytest.raises(ua.UniverseArchiveError, match="missing required"):
        ua.unpack_universe_archive(archive, tmp_path, max_dump_bytes=1 << 20)


def test_unpack_refuses_duplicate_and_non_regular_members(tmp_path):
    duplicated = tmp_path / "duplicated.tar"
    with tarfile.open(duplicated, mode="w") as writer:
        for body in (b"{}", b"{ }"):
            info = tarfile.TarInfo(ua.ARCHIVE_MEMBER_RECEIPT)
            info.size = len(body)
            writer.addfile(info, io.BytesIO(body))
    with pytest.raises(ua.UniverseArchiveError, match="repeats a member"):
        ua.unpack_universe_archive(duplicated, tmp_path, max_dump_bytes=1 << 20)

    linked = tmp_path / "linked.tar"
    with tarfile.open(linked, mode="w") as writer:
        info = tarfile.TarInfo(ua.ARCHIVE_MEMBER_DUMP)
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        writer.addfile(info)
    with pytest.raises(ua.UniverseArchiveError, match="unexpected member"):
        ua.unpack_universe_archive(linked, tmp_path, max_dump_bytes=1 << 20)


def test_unpack_refuses_oversized_dump_and_non_tar(tmp_path):
    archive = _packed(tmp_path)
    with pytest.raises(ua.UniverseArchiveError, match="limit is 4 bytes"):
        ua.unpack_universe_archive(archive, tmp_path, max_dump_bytes=4)

    not_tar = tmp_path / "not-a.tar"
    not_tar.write_bytes(b"PGDMP raw dump, not a tar")
    with pytest.raises(ua.UniverseArchiveError, match="not a readable"):
        ua.unpack_universe_archive(not_tar, tmp_path, max_dump_bytes=1 << 20)


def test_unpack_refuses_receipt_that_is_not_a_json_object(tmp_path):
    archive = _hand_rolled(
        tmp_path,
        {
            ua.ARCHIVE_MEMBER_RECEIPT: b"[1, 2]",
            ua.ARCHIVE_MEMBER_DUMP: b"PGDMP",
        },
    )
    with pytest.raises(ua.UniverseArchiveError, match="not a JSON object"):
        ua.unpack_universe_archive(archive, tmp_path, max_dump_bytes=1 << 20)


def test_verify_detects_tampered_payload(tmp_path):
    dump = tmp_path / "staged.dump"
    dump.write_bytes(b"PGDMPpayload")
    receipt = _receipt_for(dump)
    dump.write_bytes(b"PGDMPtampered")
    with pytest.raises(ua.UniverseArchiveError, match="does not match"):
        ua.verify_receipt_binds_dump(receipt, dump)


def test_verify_requires_well_formed_binding(tmp_path):
    dump = tmp_path / "staged.dump"
    dump.write_bytes(b"PGDMP")
    with pytest.raises(ua.UniverseArchiveError, match="no freeze_intent"):
        ua.verify_receipt_binds_dump({}, dump)
    with pytest.raises(ua.UniverseArchiveError, match="no archive binding"):
        ua.verify_receipt_binds_dump({"freeze_intent": {}}, dump)
    with pytest.raises(ua.UniverseArchiveError, match="malformed"):
        ua.verify_receipt_binds_dump(
            {"freeze_intent": {"archive": {"sha256": "short", "bytes": 5}}},
            dump,
        )


def test_unpacked_context_cleans_its_private_directory(tmp_path):
    artifact = _packed(tmp_path)
    with ua.unpacked_universe_archive(
        artifact, max_dump_bytes=1 << 20,
    ) as (dump, receipt):
        held = dump
        assert dump.read_bytes() == b"PGDMPpayload"
        assert receipt["freeze_intent"]["database"]["org"] == "default"
    assert not held.exists()


def test_pack_receipt_member_is_pretty_json(tmp_path):
    artifact = _packed(tmp_path)
    with tarfile.open(artifact, mode="r:") as reader:
        member = reader.extractfile(ua.ARCHIVE_MEMBER_RECEIPT)
        assert member is not None
        raw = member.read().decode("utf-8")
    dump = tmp_path / "staged.dump"
    assert raw == dumps_pretty(_receipt_for(dump)) + "\n"
