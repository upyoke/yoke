"""One-file portable universe archive: dump payload + freeze receipt.

A universe travels between deployment modes (local, self-host, hosted) as
ONE tar file named ``<org-slug>-universe-<utc-timestamp>.tar`` whose root
holds exactly two members:

* ``universe.dump`` — the ``pg_dump`` custom-format payload
  (:data:`yoke_core.domain.universe_portability.ARCHIVE_FORMAT`).
* ``freeze-receipt.json`` — the freeze receipt whose
  ``freeze_intent.archive`` block binds that exact payload by content
  hash and size.

The receipt travels inside the artifact so every importer derives its
verification from the file itself: humans move one file and are never
asked for a checksum or receipt text. Consumers verify with
:func:`verify_receipt_binds_dump`; the payload SHA-256 binds the dump
bit-for-bit, so every derived receipt figure (catalog digest, byte
count) is covered by that one comparison.
"""

from __future__ import annotations

import io
import tarfile
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from yoke_core.domain import json_helper, universe_archive_output
from yoke_core.domain.source_freeze_intent import file_sha256, freeze_intent

#: Exact member names at the archive root — the cross-repo interchange
#: contract every reader (local import, self-host import, hosted move)
#: is coded against.
ARCHIVE_MEMBER_DUMP = "universe.dump"
ARCHIVE_MEMBER_RECEIPT = "freeze-receipt.json"

#: Portable universe artifacts are ``.tar`` files.
ARTIFACT_SUFFIX = ".tar"

_RECEIPT_MEMBER_MAX_BYTES = 16 * 1024 * 1024
_COPY_CHUNK_BYTES = 1 << 20


class UniverseArchiveError(RuntimeError):
    """The one-file universe archive could not be packed or read safely."""


def build_freeze_receipt(
    *,
    database: dict[str, Any],
    frozen_at: str,
    authority: dict[str, Any],
    inspection: Any,
    zero_writable_app_sessions: bool,
) -> dict[str, Any]:
    """Compose the freeze receipt binding one inspected dump payload.

    The single receipt-assembly point for every exporter — local CLI,
    attended production cutover, and the hosted platform's server-side
    export all pass their mode's ``database`` identity, freeze moment,
    authority receipt, and the
    :class:`yoke_core.domain.universe_portability.ArchiveInspection` of
    the dump they produced; the result is the exact
    ``freeze-receipt.json`` member :func:`pack_universe_archive` writes.
    """
    from yoke_core.domain import universe_portability

    catalog = universe_portability.archive_catalog_receipt(inspection)
    intent = freeze_intent(
        database=database,
        frozen_at=frozen_at,
        authority=authority,
        archive={
            "sha256": inspection.archive_sha256,
            "bytes": inspection.size_bytes,
            "catalog_digest": inspection.catalog_digest,
        },
        zero_writable_app_sessions=zero_writable_app_sessions,
    )
    return {
        "freeze_intent": intent,
        "source_authority": authority,
        "catalog": catalog,
    }


def pack_universe_archive(
    dump: Path,
    receipt: dict[str, Any],
    destination: Path,
) -> int:
    """Write the two-member tar atomically; return its final byte size.

    The receipt member is written first so streaming readers can verify
    intent before consuming the (much larger) dump payload. The tar is
    staged as a private sibling file and committed with ``os.replace``,
    so no partial artifact ever exists under the destination name.
    """
    receipt_bytes = (json_helper.dumps_pretty(receipt) + "\n").encode("utf-8")
    try:
        output = universe_archive_output.prepare_private_archive_output(
            destination
        )
    except universe_archive_output.PrivateArchiveOutputError as exc:
        raise UniverseArchiveError(str(exc)) from exc
    try:
        with output as stream:
            with tarfile.open(
                fileobj=stream, mode="w", format=tarfile.PAX_FORMAT
            ) as archive:
                archive.addfile(
                    _member(ARCHIVE_MEMBER_RECEIPT, len(receipt_bytes)),
                    io.BytesIO(receipt_bytes),
                )
                with dump.open("rb") as payload:
                    archive.addfile(
                        _member(ARCHIVE_MEMBER_DUMP, dump.stat().st_size),
                        payload,
                    )
        output.commit()
        return destination.stat().st_size
    except UniverseArchiveError:
        raise
    except universe_archive_output.PrivateArchiveOutputError as exc:
        raise UniverseArchiveError(str(exc)) from exc
    except (OSError, tarfile.TarError) as exc:
        raise UniverseArchiveError(
            f"the universe archive could not be written: {destination}"
        ) from exc
    finally:
        output.cleanup()


def unpack_universe_archive(
    archive: Path,
    work_dir: Path,
    *,
    max_dump_bytes: int,
) -> tuple[Path, dict[str, Any]]:
    """Extract exactly the dump payload and parsed receipt, fail-closed.

    Member names are never used as filesystem paths: the dump payload is
    streamed into a caller-owned private file, so a hostile archive can
    neither traverse paths nor plant unexpected content. Any member
    beyond the two expected regular files is a refusal.
    """
    if not archive.is_file():
        raise UniverseArchiveError(
            "the portable universe artifact is not a regular file"
        )
    work_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with tarfile.open(archive, mode="r:") as reader:
            members: dict[str, tarfile.TarInfo] = {}
            for member in reader:
                if member.name in members:
                    raise UniverseArchiveError(
                        "the universe archive repeats a member: "
                        f"{member.name}"
                    )
                if member.name not in (
                    ARCHIVE_MEMBER_DUMP,
                    ARCHIVE_MEMBER_RECEIPT,
                ) or not member.isreg():
                    raise UniverseArchiveError(
                        "the universe archive holds an unexpected member; "
                        f"expected exactly {ARCHIVE_MEMBER_DUMP} and "
                        f"{ARCHIVE_MEMBER_RECEIPT} at the archive root"
                    )
                members[member.name] = member
            missing = {
                ARCHIVE_MEMBER_DUMP,
                ARCHIVE_MEMBER_RECEIPT,
            } - set(members)
            if missing:
                raise UniverseArchiveError(
                    "the universe archive is missing required members: "
                    + ", ".join(sorted(missing))
                )
            receipt = _read_receipt(reader, members[ARCHIVE_MEMBER_RECEIPT])
            dump = _extract_dump(
                reader,
                members[ARCHIVE_MEMBER_DUMP],
                work_dir,
                max_dump_bytes=max_dump_bytes,
            )
            return dump, receipt
    except tarfile.TarError as exc:
        raise UniverseArchiveError(
            "the artifact is not a readable portable universe tar archive"
        ) from exc


@contextmanager
def unpacked_universe_archive(
    archive: Path,
    *,
    max_dump_bytes: int,
) -> Iterator[tuple[Path, dict[str, Any]]]:
    """Yield ``(dump_path, receipt)`` from a private temporary directory."""
    with tempfile.TemporaryDirectory(
        prefix="yoke-universe-archive-"
    ) as work_dir:
        yield unpack_universe_archive(
            archive,
            Path(work_dir),
            max_dump_bytes=max_dump_bytes,
        )


def verify_receipt_binds_dump(
    receipt: dict[str, Any],
    dump: Path,
) -> dict[str, Any]:
    """Machine-verify the receipt's binding of the dump payload.

    The receipt travels inside the archive, so verification is derived —
    never asked of the operator. Returns the verified binding
    (``sha256`` and ``bytes``) for reporting.
    """
    intent = receipt.get("freeze_intent")
    if not isinstance(intent, dict):
        raise UniverseArchiveError(
            "the universe archive receipt carries no freeze_intent"
        )
    binding = intent.get("archive")
    if not isinstance(binding, dict):
        raise UniverseArchiveError(
            "the universe archive receipt names no archive binding"
        )
    expected_sha = str(binding.get("sha256") or "")
    expected_bytes = binding.get("bytes")
    if len(expected_sha) != 64 or not isinstance(expected_bytes, int):
        raise UniverseArchiveError(
            "the universe archive receipt binding is malformed"
        )
    actual_bytes = dump.stat().st_size
    actual_sha = file_sha256(dump)
    if actual_sha != expected_sha or actual_bytes != expected_bytes:
        raise UniverseArchiveError(
            "the freeze receipt does not match the enclosed universe dump"
            " payload; the archive is corrupt or was assembled from"
            " mismatched parts"
        )
    return {"sha256": actual_sha, "bytes": actual_bytes}


def _member(name: str, size: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    info.mode = 0o600
    info.mtime = int(time.time())
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    return info


def _read_receipt(
    reader: tarfile.TarFile,
    member: tarfile.TarInfo,
) -> dict[str, Any]:
    if member.size > _RECEIPT_MEMBER_MAX_BYTES:
        raise UniverseArchiveError(
            "the universe archive freeze receipt exceeds the read limit"
        )
    stream = reader.extractfile(member)
    if stream is None:
        raise UniverseArchiveError(
            "the universe archive freeze receipt could not be read"
        )
    with stream:
        raw = stream.read(_RECEIPT_MEMBER_MAX_BYTES + 1)
    try:
        payload = json_helper.loads_text(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise UniverseArchiveError(
            "the universe archive freeze receipt is not valid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise UniverseArchiveError(
            "the universe archive freeze receipt is not a JSON object"
        )
    return payload


def _extract_dump(
    reader: tarfile.TarFile,
    member: tarfile.TarInfo,
    work_dir: Path,
    *,
    max_dump_bytes: int,
) -> Path:
    if member.size > max_dump_bytes:
        raise UniverseArchiveError(
            f"the enclosed universe dump is {member.size} bytes; "
            f"limit is {max_dump_bytes} bytes"
        )
    stream = reader.extractfile(member)
    if stream is None:
        raise UniverseArchiveError(
            "the universe archive dump payload could not be read"
        )
    destination = work_dir / ARCHIVE_MEMBER_DUMP
    with stream:
        with destination.open("wb") as sink:
            destination.chmod(0o600)
            while True:
                chunk = stream.read(_COPY_CHUNK_BYTES)
                if not chunk:
                    break
                sink.write(chunk)
    return destination


__all__ = [
    "ARCHIVE_MEMBER_DUMP",
    "ARCHIVE_MEMBER_RECEIPT",
    "ARTIFACT_SUFFIX",
    "UniverseArchiveError",
    "build_freeze_receipt",
    "pack_universe_archive",
    "unpack_universe_archive",
    "unpacked_universe_archive",
    "verify_receipt_binds_dump",
]
