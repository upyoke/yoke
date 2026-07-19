"""Preview-first Pack get/update orchestration for a project checkout."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from yoke_cli.packs.errors import PackClientError
from yoke_cli.packs.merge import plan_get, plan_update
from yoke_cli.packs.receipt import (
    empty_receipt,
    load_receipt,
    write_receipt,
)
from yoke_cli.packs.runner_support import (
    _apply_writes,
    _assert_checkout_project,
    _assert_no_cross_pack_paths,
    _call,
    _fetch_bundle,
    _public_plan,
    _receipt_record,
    _report_receipt,
)
from yoke_contracts.packs import PACK_RECEIPT_REL


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
    accepted_current_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Preview or apply one Pack get/update, including missing dependencies."""

    if operation not in {"get", "update"}:
        raise PackClientError(f"unsupported Pack operation: {operation}")
    accepted_paths = sorted(set(accepted_current_paths or []))
    if operation != "update" and accepted_paths:
        raise PackClientError("--accept-current is available only for Pack updates")
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
            _accept_current_conflicts(plan, accepted_paths)
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


def _accept_current_conflicts(plan: dict[str, Any], accepted_paths: list[str]) -> None:
    if not accepted_paths:
        plan["accepted_current"] = []
        return
    conflicts = {row["path"]: row for row in plan["conflicts"]}
    unknown = sorted(set(accepted_paths) - set(conflicts))
    if unknown:
        joined = ", ".join(unknown)
        raise PackClientError(
            f"--accept-current path is not an unresolved Pack conflict: {joined}"
        )
    accepted = set(accepted_paths)
    plan["accepted_current"] = [
        row for row in plan["conflicts"] if row["path"] in accepted
    ]
    plan["conflicts"] = [
        row for row in plan["conflicts"] if row["path"] not in accepted
    ]
    plan["changed"] = bool(plan["changed"] or plan["accepted_current"])


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


__all__ = ["PackClientError", "list_packs", "run_pack_operation"]
