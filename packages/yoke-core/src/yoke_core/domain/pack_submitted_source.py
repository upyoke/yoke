"""Render a Pack bundle from client-submitted pre-release Pack source.

The served catalog is the connected control plane's installed release. A Pack
author's lane, or a commit already merged but not yet released, is visible
only to the client, so the client submits that one Pack's source tree and the
server renders it with the same validation and project render values the
served catalog uses.
"""

from __future__ import annotations

import base64
import binascii
from pathlib import Path, PurePosixPath
import tempfile
from typing import Any, Mapping

from yoke_contracts.packs import (
    PACK_CATALOG_SERVED,
    PACK_SUBMITTED_SOURCE_MAX_BYTES,
    validate_pack_source,
)
from yoke_core.domain.pack_catalog import PackError, build_pack_bundle


def render_submitted_pack_bundle(
    conn: Any,
    *,
    project: str,
    pack: str,
    source: Mapping[str, Any],
    files: list[Mapping[str, str]],
    version: str | None = None,
    render_values: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Render *pack* from submitted ``packs/``-relative source files."""

    try:
        catalog = validate_pack_source(source)
    except ValueError as exc:
        raise PackError(f"submitted Pack source is invalid: {exc}") from exc
    if catalog["kind"] == PACK_CATALOG_SERVED:
        raise PackError(
            "submitted Pack source cannot claim the served catalog; "
            "use packs.bundle.get for served Pack versions"
        )
    decoded = _decode_files(pack, files)
    with tempfile.TemporaryDirectory(prefix="yoke-pack-source-") as raw_root:
        packs_dir = Path(raw_root)
        for relative, content in decoded.items():
            target = packs_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        bundle = build_pack_bundle(
            conn,
            project=project,
            pack=pack,
            version=version,
            render_values=render_values,
            packs_dir=packs_dir,
        )
    bundle["catalog"] = catalog
    return bundle


def _decode_files(pack: str, files: list[Mapping[str, str]]) -> dict[str, bytes]:
    decoded: dict[str, bytes] = {}
    total = 0
    for entry in files:
        raw_path = str(entry.get("path") or "")
        relative = PurePosixPath(raw_path)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or len(relative.parts) < 2
            or relative.parts[0] != pack
        ):
            raise PackError(
                f"submitted Pack source path {raw_path!r} is outside Pack {pack!r}"
            )
        if raw_path in decoded:
            raise PackError(f"submitted Pack source repeats {raw_path!r}")
        try:
            content = base64.b64decode(
                str(entry.get("content") or "").encode("ascii"), validate=True
            )
        except (ValueError, binascii.Error) as exc:
            raise PackError(
                f"submitted Pack source {raw_path!r} is not base64"
            ) from exc
        total += len(content)
        if total > PACK_SUBMITTED_SOURCE_MAX_BYTES:
            raise PackError(
                f"submitted Pack source for {pack!r} exceeds "
                f"{PACK_SUBMITTED_SOURCE_MAX_BYTES} bytes"
            )
        decoded[raw_path] = content
    if f"{pack}/pack.json" not in decoded:
        raise PackError(f"submitted Pack source for {pack!r} has no pack.json")
    return decoded


__all__ = ["render_submitted_pack_bundle"]
