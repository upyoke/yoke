"""``yoke projects ...`` read adapters + ``yoke project-structure patch apply``.

Function ids handled here:

* ``projects.get`` — read one project field (or the full row).
* ``projects.list`` — list project inventory rows visible to the actor.
* ``projects.resolve_by_github_repo`` — resolve a repo to a visible project.
* ``projects.capability.has`` — boolean capability presence check.
* ``projects.checkout_context.run`` — which project this checkout is in.
* ``project_structure.patch.apply`` — apply a JSON-shaped patch op list.

The write pair (``projects.create`` / ``projects.update``) lives in the
sibling :mod:`yoke_cli.commands.adapters.projects_write`.
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List

from yoke_contracts.project_context import CHECKOUT_CONTEXT_FIELDS
from yoke_cli.commands._helpers import (
    add_json_arg,
    add_project_arg,
    add_session_arg,
    client_project_context,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef


__all__ = [
    "projects_get", "projects_list", "projects_resolve_by_github_repo",
    "projects_capability_has",
    "projects_checkout_context",
    "project_structure_patch_apply",
    "PROJECTS_GET_USAGE", "PROJECTS_LIST_USAGE",
    "PROJECTS_RESOLVE_BY_GITHUB_REPO_USAGE",
    "PROJECTS_CAPABILITY_HAS_USAGE",
    "PROJECTS_CHECKOUT_CONTEXT_USAGE",
    "PROJECT_STRUCTURE_PATCH_APPLY_USAGE",
]


PROJECTS_GET_USAGE = (
    "yoke projects get --project NAME [--field FIELD] [--session-id S] [--json]"
)


def projects_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke projects get", description=PROJECTS_GET_USAGE,
    )
    parser.add_argument("--project", required=True, help="Project name.")
    parser.add_argument("--field", default=None,
                        help="Optional field projection (single column).")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, PROJECTS_GET_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {"project": parsed.project}
    if parsed.field:
        payload["field"] = parsed.field

    def _human_writer(response, stdout, stderr) -> None:
        if not response.success:
            return None
        result = response.result or {}
        if parsed.field:
            value = result.get("value")
            text = "" if value is None else str(value)
            stdout.write(text)
            if not text.endswith("\n"):
                stdout.write("\n")
            return None
        print(json.dumps(result, sort_keys=True), file=stdout)
        return None

    return dispatch_and_emit(
        function_id="projects.get",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id, json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


PROJECTS_LIST_USAGE = "yoke projects list [--session-id S] [--json]"


def projects_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke projects list", description=PROJECTS_LIST_USAGE,
    )
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, PROJECTS_LIST_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        if not response.success:
            return None
        result = response.result or {}
        fields = result.get("fields") or []
        rows = result.get("rows") or []
        for row in rows:
            print(
                "|".join(
                    "" if row.get(field) is None else str(row.get(field))
                    for field in fields
                ),
                file=stdout,
            )
        return None

    return dispatch_and_emit(
        function_id="projects.list",
        target=TargetRef(kind="global"),
        payload={},
        session_id=parsed.session_id, json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


PROJECTS_RESOLVE_BY_GITHUB_REPO_USAGE = (
    "yoke projects resolve-by-github-repo --github-repo OWNER/REPO "
    "[--session-id S] [--json]"
)


def projects_resolve_by_github_repo(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke projects resolve-by-github-repo",
        description=PROJECTS_RESOLVE_BY_GITHUB_REPO_USAGE,
    )
    parser.add_argument("--github-repo", dest="github_repo", required=True)
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser,
        args,
        PROJECTS_RESOLVE_BY_GITHUB_REPO_USAGE,
    )
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        if not response.success:
            return None
        print(json.dumps(response.result or {}, sort_keys=True), file=stdout)
        return None

    return dispatch_and_emit(
        function_id="projects.resolve_by_github_repo",
        target=TargetRef(kind="global"),
        payload={"github_repo": parsed.github_repo},
        session_id=parsed.session_id, json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


PROJECTS_CHECKOUT_CONTEXT_USAGE = (
    "yoke projects checkout-context "
    "[--field id|slug|name|public_item_prefix] [--project P] "
    "[--session-id S] [--json]"
)


def projects_checkout_context(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke projects checkout-context",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Resolve which project this checkout is standing in and print "
            "id|slug|name|public_item_prefix (or one --field). The mapping "
            "resolves client-side (--project flag > $YOKE_PROJECT > the "
            "machine-config checkout→project map; `yoke project register` "
            "records the mapping); the server enriches it with the projects "
            "row, falling back to session inference when no hint resolves. "
            "Works over https and from any cwd — no checkout import path, "
            "no direct DB connection."
        ),
        epilog=(
            "Example (the strategize/feed preamble):\n"
            "  _project=$(yoke projects checkout-context --field slug)\n"
            "  _project_id=$(yoke projects checkout-context --field id)\n"
            "  _prefix=$(yoke projects checkout-context "
            "--field public_item_prefix)"
        ),
    )
    parser.add_argument(
        "--field", default=None, choices=CHECKOUT_CONTEXT_FIELDS,
        help="Print just this field's value (bare, newline-terminated).",
    )
    add_project_arg(parser); add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, PROJECTS_CHECKOUT_CONTEXT_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        if not response.success:
            return None
        result = response.result or {}
        if parsed.field:
            value = result.get(parsed.field)
            print("" if value is None else str(value), file=stdout)
            return None
        print(
            "|".join(
                "" if result.get(k) is None else str(result.get(k))
                for k in CHECKOUT_CONTEXT_FIELDS
            ),
            file=stdout,
        )
        return None

    return dispatch_and_emit(
        function_id="projects.checkout_context.run",
        target=TargetRef(
            kind="global",
            project_id=client_project_context(parsed.project),
        ),
        payload={},
        session_id=parsed.session_id, json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


PROJECTS_CAPABILITY_HAS_USAGE = (
    "yoke projects capability has --project NAME --cap-type TYPE "
    "[--session-id S] [--json]"
)


def projects_capability_has(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke projects capability has",
        description=PROJECTS_CAPABILITY_HAS_USAGE,
    )
    parser.add_argument("--project", required=True, help="Project name.")
    parser.add_argument("--cap-type", dest="cap_type", required=True,
                        help="Capability type to test for presence.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, PROJECTS_CAPABILITY_HAS_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="projects.capability.has",
        target=TargetRef(kind="global"),
        payload={"project": parsed.project, "cap_type": parsed.cap_type},
        session_id=parsed.session_id, json_mode=parsed.json_mode,
    )


PROJECT_STRUCTURE_PATCH_APPLY_USAGE = (
    "yoke project-structure patch apply --project NAME "
    "--ops-json JSON [--actor ACTOR] [--session-id S] [--json]"
)


def project_structure_patch_apply(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke project-structure patch apply",
        description=PROJECT_STRUCTURE_PATCH_APPLY_USAGE,
    )
    parser.add_argument("--project", required=True, help="Project id.")
    parser.add_argument("--ops-json", dest="ops_json", required=True,
                        help="JSON array of patch op dicts.")
    parser.add_argument("--actor", default=None,
                        help="Optional actor override (defaults to session actor).")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, PROJECT_STRUCTURE_PATCH_APPLY_USAGE)
    if parsed is None:
        return 2
    try:
        ops = json.loads(parsed.ops_json)
    except json.JSONDecodeError as exc:
        return usage_error(f"--ops-json invalid: {exc}")
    if not isinstance(ops, list):
        return usage_error("--ops-json must be a JSON array")
    payload: Dict[str, Any] = {"project_id": parsed.project, "ops": ops}
    if parsed.actor:
        payload["actor"] = parsed.actor
    return dispatch_and_emit(
        function_id="project_structure.patch.apply",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id, json_mode=parsed.json_mode,
    )
