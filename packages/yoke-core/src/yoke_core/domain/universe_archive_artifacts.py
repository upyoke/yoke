"""Manifest-bound optional files in a portable universe archive."""

from __future__ import annotations

import hashlib
import io
import json
import re
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any

from yoke_contracts.qa_artifact_limits import (
    MAX_ARTIFACT_MANIFEST_BYTES,
)

MANIFEST = "artifacts-manifest.json"
_DIGEST = re.compile(r"[0-9a-f]{64}")


def _refuse(detail: str) -> None:
    from yoke_core.domain.universe_archive import UniverseArchiveError

    raise UniverseArchiveError(
        f"archive_artifacts_invalid: {detail}; export the source again"
    )


def safe_key(value: Any) -> str:
    if not isinstance(value, str):
        _refuse("artifact key must be a string")
    parts = value.split("/")
    if (
        len(parts) < 2
        or parts[0] not in {"qa-artifacts", "shared-files"}
        or any(p in {"", ".", ".."} or "\\" in p for p in parts)
        or str(PurePosixPath(value)) != value
    ):
        _refuse("unsafe artifact key")
    return value


def allowed_member(member: tarfile.TarInfo) -> bool:
    if not member.isreg():
        return False
    if member.name == MANIFEST:
        return member.size <= MAX_ARTIFACT_MANIFEST_BYTES
    if member.name.startswith("artifacts/"):
        safe_key(member.name.removeprefix("artifacts/"))
        return member.size >= 0
    return False


def manifest_bytes(manifest: dict) -> bytes:
    return (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()


def bind_manifest(receipt: dict, manifest: dict) -> dict:
    """Include optional files in the receipt identity as well as its binding."""
    import copy

    result = copy.deepcopy(receipt)
    intent = result["freeze_intent"]
    intent["archive"]["artifacts_manifest_sha256"] = hashlib.sha256(
        manifest_bytes(manifest)
    ).hexdigest()
    if "receipt_id" in intent:
        body = {k: v for k, v in intent.items() if k != "receipt_id"}
        intent["receipt_id"] = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    return result


def pack_files(
    reader: tarfile.TarFile, receipt: dict, manifest: dict, files: dict[str, Path]
) -> None:
    from yoke_core.domain.universe_archive import _member

    raw = manifest_bytes(manifest)
    if len(raw) > MAX_ARTIFACT_MANIFEST_BYTES:
        _refuse("manifest exceeds its read limit")
    reader.addfile(_member(MANIFEST, len(raw)), io.BytesIO(raw))
    for key, path in files.items():
        safe_key(key)
        with path.open("rb") as stream:
            reader.addfile(_member("artifacts/" + key, path.stat().st_size), stream)


def unpack_files(
    reader: tarfile.TarFile,
    members: dict,
    receipt: dict,
    work_dir: Path,
    *,
    max_bytes: int,
) -> dict | None:
    """Verify the full manifest and content before exposing any imported file."""
    intent = receipt.get("freeze_intent", {})
    if not isinstance(intent, dict) or not isinstance(intent.get("archive", {}), dict):
        _refuse("freeze receipt archive binding is invalid")
    binding = intent.get("archive", {})
    extra = set(members) - {"universe.dump", "freeze-receipt.json"}
    if MANIFEST not in members:
        if extra or "artifacts_manifest_sha256" in binding:
            _refuse("artifact manifest is missing")
        return None
    stream = reader.extractfile(members[MANIFEST])
    with stream:
        raw = stream.read(MAX_ARTIFACT_MANIFEST_BYTES + 1)
    if hashlib.sha256(raw).hexdigest() != binding.get("artifacts_manifest_sha256"):
        _refuse("freeze receipt does not bind the artifact manifest")
    try:
        manifest = json.loads(raw)
    except (ValueError, UnicodeError):
        _refuse("manifest is not JSON")
    if (
        not isinstance(manifest, dict)
        or manifest.get("version") != 1
        or not isinstance(manifest.get("entries"), list)
    ):
        _refuse("manifest schema is invalid")
    expected = {MANIFEST}
    seen: set[str] = set()
    total = 0
    for entry in manifest["entries"]:
        if not isinstance(entry, dict):
            _refuse("manifest entry is not an object")
        key = safe_key(entry.get("key"))
        if key in seen:
            _refuse("manifest repeats an artifact key")
        seen.add(key)
        if entry.get("status") == "missing":
            if not isinstance(entry.get("reason"), str) or not entry["reason"]:
                _refuse("missing artifact has no reason")
            continue
        size, digest = entry.get("bytes"), entry.get("sha256")
        if (
            entry.get("status") != "included"
            or type(size) is not int
            or size < 0
            or not isinstance(digest, str)
            or not _DIGEST.fullmatch(digest)
        ):
            _refuse("artifact size, digest or status is invalid")
        name = "artifacts/" + key
        expected.add(name)
        member = members.get(name)
        if member is None or member.size != size:
            _refuse("artifact is missing or has the wrong size")
        total += size
        if total > max_bytes:
            _refuse("artifact bytes exceed the import limit")
        target = work_dir / name
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        digestor = hashlib.sha256()
        stream = reader.extractfile(member)
        with stream, target.open("xb") as sink:
            target.chmod(0o600)
            while chunk := stream.read(1 << 20):
                digestor.update(chunk)
                sink.write(chunk)
        if digestor.hexdigest() != digest:
            _refuse("artifact checksum differs from its manifest")
    if extra != expected:
        _refuse("archive contains unmanifested artifact files")
    (work_dir / MANIFEST).write_bytes(raw)
    (work_dir / MANIFEST).chmod(0o600)
    return manifest


def summary(dump: Path) -> dict:
    path = dump.parent / MANIFEST
    if not path.is_file():
        return {"manifest": False, "included": 0, "missing": []}
    entries = json.loads(path.read_bytes())["entries"]
    return {
        "manifest": True,
        "included": sum(e["status"] == "included" for e in entries),
        "missing": [
            {"key": e["key"], "reason": e["reason"]}
            for e in entries
            if e["status"] == "missing"
        ],
    }
