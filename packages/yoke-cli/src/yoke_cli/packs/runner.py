"""Preview-first Pack get/update orchestration for a project checkout."""

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
from yoke_cli.packs.merge import plan_get, plan_update
from yoke_cli.packs.receipt import (
    assert_pack_targets_safe,
    empty_receipt,
    load_receipt,
    write_receipt,
)
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.packs import PACK_BUNDLE_SCHEMA, PACK_RECEIPT_REL


class PackClientError(RuntimeError):
    """A Pack operation cannot proceed; the message names the repair."""


def list_packs(*, project: str, session_id: str | None = None) -> dict[str, Any]:
    return _call("packs.catalog.list", {"project": project}, session_id=session_id)


def run_pack_operation(
    repo_root: str | Path | None,
    *,
    project: str,
    pack: str,
    operation: str,
    apply: bool = False,
    version: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Preview or apply one Pack get/update, including missing dependencies."""

    if operation not in {"get", "update"}:
        raise PackClientError(f"unsupported Pack operation: {operation}")
    root = Path(repo_root or os.getcwd()).expanduser().resolve()
    if not root.is_dir():
        raise PackClientError(f"project checkout is not a directory: {root}")
    receipt = load_receipt(root)
    requested = _fetch_bundle(project, pack, version=version, session_id=session_id)
    _assert_checkout_project(root, requested, receipt)
    if receipt is None:
        receipt = empty_receipt(requested["project_id"], requested["project_slug"])
    installed = receipt["packs"]
    if operation == "get" and pack in installed:
        raise PackClientError(
            f"Pack {pack!r} is already installed at {installed[pack]['version']}; use update"
        )
    if operation == "update" and pack not in installed:
        raise PackClientError(f"Pack {pack!r} is not installed; use get")

    bundles: list[dict[str, Any]] = []
    if operation == "get":
        _collect_missing_dependencies(
            project,
            requested,
            installed,
            bundles,
            set(),
            session_id=session_id,
        )
    bundles.append(requested)

    plans: list[dict[str, Any]] = []
    execution_plans: list[dict[str, Any]] = []
    simulated = json.loads(json.dumps(receipt))
    for bundle in bundles:
        slug = bundle["pack"]
        _assert_no_cross_pack_paths(simulated, slug, bundle["files"])
        if slug in simulated["packs"]:
            old_version = simulated["packs"][slug]["version"]
            old_bundle = _fetch_bundle(
                project,
                slug,
                version=old_version,
                render_values=simulated["packs"][slug]["render_values"],
                session_id=session_id,
            )
            plan = plan_update(root, old_bundle["files"], bundle["files"])
            action = "update"
            from_version = old_version
        else:
            plan = plan_get(root, bundle["files"])
            action = "get"
            from_version = None
        plans.append(
            {
                "pack": slug,
                "operation": action,
                "from_version": from_version,
                "to_version": bundle["version"],
                "plan": _public_plan(plan),
            }
        )
        execution_plans.append(plan)
        simulated["packs"][slug] = _receipt_record(bundle)

    conflict_count = sum(len(row["plan"]["conflicts"]) for row in plans)
    report: dict[str, Any] = {
        "operation": operation,
        "project_id": requested["project_id"],
        "project_slug": requested["project_slug"],
        "repo_root": str(root),
        "requested_pack": pack,
        "plans": plans,
        "conflict_count": conflict_count,
        "applied": False,
        "receipt": str(root / PACK_RECEIPT_REL),
    }
    if not apply or conflict_count:
        report["refused"] = bool(apply and conflict_count)
        return report

    for execution_plan in execution_plans:
        _apply_writes(root, execution_plan)
    write_receipt(root, simulated)
    report["applied"] = True
    report["refused"] = False
    try:
        report["projection"] = _report_receipt(
            project, simulated, session_id=session_id
        )
    except PackClientError as exc:
        report["projection"] = None
        report["projection_warning"] = str(exc)
    return report


def _collect_missing_dependencies(
    project: str,
    bundle: Mapping[str, Any],
    installed: Mapping[str, Any],
    output: list[dict[str, Any]],
    visiting: set[str],
    *,
    session_id: str | None,
) -> None:
    slug = str(bundle["pack"])
    if slug in visiting:
        raise PackClientError(f"Pack dependency cycle includes {slug!r}")
    visiting.add(slug)
    for dependency in bundle["dependencies"]:
        if dependency in installed or any(row["pack"] == dependency for row in output):
            continue
        dependency_bundle = _fetch_bundle(
            project, dependency, version=None, session_id=session_id
        )
        _collect_missing_dependencies(
            project,
            dependency_bundle,
            installed,
            output,
            visiting,
            session_id=session_id,
        )
        output.append(dependency_bundle)
    visiting.remove(slug)


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
            raise PackClientError(f"Pack bundle encoding is invalid for {path!r}") from exc
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
        raise PackClientError("Pack operations require a checkout registered to a Yoke project")
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
        path: slug
        for slug, record in receipt["packs"].items()
        if slug != selected_slug
        for path in record["files"]
    }
    overlap = sorted(entry["path"] for entry in entries if entry["path"] in owners)
    if overlap:
        details = ", ".join(f"{path} ({owners[path]})" for path in overlap)
        raise PackClientError(f"Pack file overlap must be resolved in the catalog: {details}")


def _receipt_record(bundle: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "version": bundle["version"],
        "content_digest": bundle["content_digest"],
        "render_values": dict(bundle["render_values"]),
        "files": {
            entry["path"]: {"sha256": entry["sha256"], "mode": entry["mode"]}
            for entry in bundle["files"]
        },
    }


def _public_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "creates": [row["path"] for row in plan["creates"]],
        "updates": [row["path"] for row in plan["updates"]],
        "unchanged": list(plan["unchanged"]),
        "conflicts": list(plan["conflicts"]),
        "retained_project_files": list(plan["retained_project_files"]),
        "changed": bool(plan["changed"]),
    }


def _apply_writes(
    repo_root: Path,
    plan: Mapping[str, Any],
) -> None:
    writes = {
        entry["path"]: entry
        for entry in [*plan["creates"], *plan["updates"]]
    }
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
    receipt_bytes = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
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


__all__ = ["PackClientError", "list_packs", "run_pack_operation"]
