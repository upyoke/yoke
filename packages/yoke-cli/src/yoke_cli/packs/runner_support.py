"""Bundle transport, validation, checkout checks, and writes for Pack operations."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

from yoke_cli.commands._helpers import ensure_handlers_loaded
from yoke_cli.config import existing_project_lookup
from yoke_cli.packs.errors import PackClientError
from yoke_cli.packs.receipt import assert_pack_targets_safe
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.packs import PACK_BUNDLE_SCHEMA


def _fetch_bundle(
    project: str,
    pack: str,
    *,
    version: str | None,
    render_values: Mapping[str, str] | None = None,
    session_id: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"project": project, "pack": pack}
    if version is not None:
        payload["version"] = version
    if render_values is not None:
        payload["render_values"] = dict(render_values)
    bundle = _call("packs.bundle.get", payload, session_id=session_id)
    _validate_bundle(bundle)
    return bundle


def _call(
    function_id: str,
    payload: dict[str, Any],
    *,
    session_id: str | None,
) -> dict[str, Any]:
    ensure_handlers_loaded()
    response = call_dispatcher(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload=payload,
        actor=build_actor(session_id=session_id),
        timeout_s=60,
    )
    if not response.success:
        message = (
            f"{response.error.code}: {response.error.message}"
            if response.error
            else f"{function_id} failed"
        )
        raise PackClientError(message)
    if not isinstance(response.result, dict):
        raise PackClientError(f"{function_id} returned no result object")
    return dict(response.result)


def _validate_bundle(bundle: Mapping[str, Any]) -> None:
    if bundle.get("bundle_schema") != PACK_BUNDLE_SCHEMA:
        raise PackClientError("Pack bundle schema is unsupported")
    for key in ("pack", "version", "latest_version", "project_slug", "content_digest"):
        if not isinstance(bundle.get(key), str) or not bundle[key]:
            raise PackClientError(f"Pack bundle {key} is missing")
    if not isinstance(bundle.get("project_id"), int) or bundle["project_id"] <= 0:
        raise PackClientError("Pack bundle project_id is invalid")
    if not isinstance(bundle.get("dependencies"), list):
        raise PackClientError("Pack bundle dependencies are invalid")
    render_values = bundle.get("render_values")
    if not isinstance(render_values, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in render_values.items()
    ):
        raise PackClientError("Pack bundle render_values are invalid")
    files = bundle.get("files")
    if not isinstance(files, list):
        raise PackClientError("Pack bundle files are invalid")
    seen: set[str] = set()
    material: list[dict[str, Any]] = []
    for entry in files:
        if not isinstance(entry, Mapping):
            raise PackClientError("Pack bundle file record is invalid")
        path = entry.get("path")
        content = entry.get("content")
        encoding = entry.get("encoding")
        digest = entry.get("sha256")
        mode = entry.get("mode")
        if not isinstance(path, str) or path in seen:
            raise PackClientError("Pack bundle contains a duplicate or invalid path")
        seen.add(path)
        if not isinstance(content, str) or encoding not in {"utf-8", "base64"}:
            raise PackClientError(f"Pack bundle content is invalid for {path!r}")
        try:
            raw_content = (
                content.encode("utf-8")
                if encoding == "utf-8"
                else base64.b64decode(content.encode("ascii"), validate=True)
            )
        except (ValueError, UnicodeEncodeError) as exc:
            raise PackClientError(
                f"Pack bundle encoding is invalid for {path!r}"
            ) from exc
        if hashlib.sha256(raw_content).hexdigest() != digest:
            raise PackClientError(f"Pack bundle content digest is invalid for {path!r}")
        if mode not in (0o644, 0o755):
            raise PackClientError(f"Pack bundle mode is invalid for {path!r}")
        material.append(
            {"path": path, "sha256": digest, "mode": mode, "encoding": encoding}
        )
    encoded = json.dumps(material, separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(encoded).hexdigest() != bundle["content_digest"]:
        raise PackClientError("Pack bundle content_digest does not match its files")


def _assert_checkout_project(
    repo_root: Path,
    bundle: Mapping[str, Any],
    receipt: Mapping[str, Any] | None,
) -> None:
    try:
        reference = existing_project_lookup.find_local_project_reference(
            repo_root, config_path=None
        )
    except existing_project_lookup.ExistingProjectLookupError as exc:
        raise PackClientError(str(exc)) from exc
    if reference is None:
        raise PackClientError(
            "Pack operations require a checkout registered to a Yoke project"
        )
    if reference.project_id != bundle["project_id"]:
        raise PackClientError("checkout project binding does not match the Pack bundle")
    if receipt is not None and (
        receipt["project_id"] != bundle["project_id"]
        or receipt["project_slug"] != bundle["project_slug"]
    ):
        raise PackClientError("Pack receipt belongs to a different project")


def _assert_no_cross_pack_paths(
    receipt: Mapping[str, Any],
    selected_slug: str,
    entries: list[dict[str, Any]],
) -> None:
    owners = {
        file_record["path"]: slug
        for slug, record in receipt["packs"].items()
        if slug != selected_slug
        for file_record in record["files"].values()
    }
    overlap = sorted(entry["path"] for entry in entries if entry["path"] in owners)
    if overlap:
        details = ", ".join(f"{path} ({owners[path]})" for path in overlap)
        raise PackClientError(
            f"Pack file overlap must be resolved in the catalog: {details}"
        )


def _project_entries(
    entries: list[dict[str, Any]],
    receipt_record: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Map Pack-defined file identities to their current project locations."""
    recorded_files = (
        receipt_record.get("files", {}) if receipt_record is not None else {}
    )
    mapped: list[dict[str, Any]] = []
    for entry in entries:
        row = dict(entry)
        recorded = recorded_files.get(entry["path"], {})
        if isinstance(recorded, Mapping):
            row["path"] = str(recorded.get("path") or entry["path"])
        mapped.append(row)
    return mapped


def _receipt_record(
    bundle: Mapping[str, Any],
    previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    previous_files = previous.get("files", {}) if previous is not None else {}
    return {
        "version": bundle["version"],
        "content_digest": bundle["content_digest"],
        "render_values": dict(bundle["render_values"]),
        "files": {
            entry["path"]: {
                "path": (
                    previous_files.get(entry["path"], {}).get("path")
                    if isinstance(previous_files.get(entry["path"]), Mapping)
                    else None
                )
                or entry["path"],
                "sha256": entry["sha256"],
                "mode": entry["mode"],
            }
            for entry in bundle["files"]
        },
    }


def _public_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "creates": [row["path"] for row in plan["creates"]],
        "updates": [row["path"] for row in plan["updates"]],
        "unchanged": list(plan["unchanged"]),
        "conflicts": list(plan["conflicts"]),
        "accepted_current": list(plan.get("accepted_current", [])),
        "retained_project_files": list(plan["retained_project_files"]),
        "changed": bool(plan["changed"]),
    }


def _apply_writes(repo_root: Path, plan: Mapping[str, Any]) -> None:
    writes = {entry["path"]: entry for entry in [*plan["creates"], *plan["updates"]]}
    assert_pack_targets_safe(repo_root, list(writes))
    for path, entry in sorted(writes.items()):
        target = repo_root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, raw_temp = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        temp = Path(raw_temp)
        try:
            payload = (
                entry["content"].encode("utf-8")
                if entry.get("encoding", "utf-8") == "utf-8"
                else base64.b64decode(entry["content"].encode("ascii"))
            )
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            temp.chmod(entry["mode"])
            os.replace(temp, target)
        finally:
            if temp.exists():
                temp.unlink()


def _report_receipt(
    project: str,
    receipt: Mapping[str, Any],
    *,
    session_id: str | None,
) -> dict[str, Any]:
    receipt_bytes = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    return _call(
        "packs.project.report",
        {
            "project": project,
            "receipt_digest": hashlib.sha256(receipt_bytes).hexdigest(),
            "packs": [
                {
                    "slug": slug,
                    "version": record["version"],
                    "file_count": len(record["files"]),
                }
                for slug, record in sorted(receipt["packs"].items())
            ],
        },
        session_id=session_id,
    )


__all__ = [
    "_apply_writes",
    "_assert_checkout_project",
    "_assert_no_cross_pack_paths",
    "_call",
    "_fetch_bundle",
    "_public_plan",
    "_project_entries",
    "_receipt_record",
    "_report_receipt",
]
