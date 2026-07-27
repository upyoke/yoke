"""Interactive full-document editing for project QA plans."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, List

from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)
from yoke_cli.commands import _helpers
from yoke_cli.commands._helpers import (
    add_json_arg,
    add_project_arg,
    add_session_arg,
    client_project_context,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher, emit_response


QA_PLAN_EDIT_USAGE = (
    "yoke qa plan edit PLAN_SLUG [--project P] [--editor COMMAND] "
    "[--session-id S] [--json]"
)
_QA_PLAN_EDIT_HELP_DEEP = """\
Open a clean JSON authoring document and save the whole plan atomically.

Worked example:

  yoke qa plan edit release-readiness --project yoke --editor "code --wait"

CAS and recovery:
  The command submits the updated_at token read before the editor opened.
  If another writer saves first, the stale edit is refused without partial
  changes. Reopen the command on the latest plan and reapply the intended edit.
  Editor, document-validation, and save failures preserve the temporary JSON.

Flag guidance:
  PLAN_SLUG     required, immutable plan slug
  --project     project slug/id; defaults to checkout or YOKE_PROJECT context
  --editor      command; defaults to $VISUAL, $EDITOR, then vi
  --session-id  optional operator-debug session identity
  --json        emit a typed response envelope on stdout

Exit codes: 0 saved or unchanged; 1 editor, validation, CAS, or dispatch failure;
2 command-line usage error.
"""
_DOCUMENT_KEYS = {
    "slug",
    "name",
    "description",
    "success_policy_id",
    "success_policy_params",
    "cases",
}
_CASE_KEYS = (
    "case_key",
    "position",
    "method_id",
    "instructions",
    "expected_outcome",
    "method_config",
    "success_policy_id",
    "success_policy_params",
    "host_baselines",
    "entry_surface",
    "required_completion",
)


def _authoring_document(plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan.get("slug"), str) or not plan["slug"]:
        raise ValueError("qa.plan.get returned an invalid plan slug")
    if not isinstance(plan.get("name"), str):
        raise ValueError("qa.plan.get returned an invalid plan name")
    cases = plan.get("cases")
    if not isinstance(cases, list) or any(not isinstance(case, dict) for case in cases):
        raise ValueError("qa.plan.get returned an invalid plan case list")
    return {
        "slug": plan["slug"],
        "name": plan["name"],
        "description": plan.get("description", ""),
        "success_policy_id": plan.get("success_policy_id", "all-pass"),
        "success_policy_params": plan.get("success_policy_params") or {},
        "cases": [
            {
                key: (
                    case.get(key, [])
                    if key == "host_baselines"
                    else case.get(key, {})
                    if key == "method_config"
                    else case.get(key)
                )
                for key in _CASE_KEYS
            }
            for case in cases
        ],
    }


def _write_document(slug: str, document: dict[str, Any]) -> Path:
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=f"yoke-qa-plan-{slug}-",
        suffix=".json",
        delete=False,
    ) as stream:
        json.dump(document, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
        return Path(stream.name)


def _editor_argv(explicit: str | None) -> list[str]:
    command = explicit or os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        raise ValueError(f"invalid editor command: {exc}") from exc
    if not argv:
        raise ValueError("editor command must not be empty")
    return argv


def _preserved(path: Path, reason: str) -> None:
    print(f"{reason}; edited document preserved at {path}", file=sys.stderr)


def _client_failure(
    *,
    code: str,
    message: str,
    json_mode: bool,
    preserved_path: Path | None = None,
) -> int:
    if preserved_path is not None:
        message = f"{message}; edited document preserved at {preserved_path}"
    response = FunctionCallResponse(
        success=False,
        function="qa.plan.edit",
        version="v1",
        request_id=str(uuid.uuid4()),
        error=FunctionError(code=code, message=message),
    )
    return emit_response(response, json_mode=json_mode)


def _load_edited_document(path: Path, slug: str) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"edited plan is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ValueError("edited plan must be a JSON object")
    missing = sorted(_DOCUMENT_KEYS - set(document))
    extra = sorted(set(document) - _DOCUMENT_KEYS)
    if missing or extra:
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        raise ValueError("edited plan fields are invalid: " + "; ".join(details))
    if document["slug"] != slug:
        raise ValueError(
            f"plan slug is immutable; expected {slug!r}, found {document['slug']!r}"
        )
    return document


def qa_plan_edit(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa plan edit",
        description=(f"{QA_PLAN_EDIT_USAGE}\n\n{_QA_PLAN_EDIT_HELP_DEEP}"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("slug")
    add_project_arg(parser)
    parser.add_argument(
        "--editor",
        default=None,
        help="Editor command (default: $VISUAL, then $EDITOR, then vi).",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, QA_PLAN_EDIT_USAGE)
    if parsed is None:
        return 2

    project = client_project_context(parsed.project)
    if project is None:
        return usage_error(
            "project context required: pass --project P, set YOKE_PROJECT, "
            "or run from a checkout mapped in machine config"
        )

    _helpers.ensure_handlers_loaded()
    actor = build_actor(session_id=parsed.session_id)
    target = TargetRef(kind="global")
    listed = call_dispatcher(
        function_id="qa.plan.list",
        target=target,
        payload={"project": project},
        actor=actor,
    )
    if not listed.success:
        return emit_response(listed, json_mode=parsed.json_mode)
    rows = (listed.result or {}).get("rows")
    if not isinstance(rows, list) or any(
        not isinstance(candidate, dict) for candidate in rows
    ):
        return _client_failure(
            code="invalid_response",
            message="qa.plan.list returned an invalid plan roster",
            json_mode=parsed.json_mode,
        )
    row = next(
        (candidate for candidate in rows if candidate.get("slug") == parsed.slug),
        None,
    )
    if row is None:
        return _client_failure(
            code="not_found",
            message=(f"QA plan {parsed.slug!r} was not found in project {project!r}"),
            json_mode=parsed.json_mode,
        )
    try:
        plan_id = int(row["id"])
        project = str(row.get("project") or project)
    except (KeyError, TypeError, ValueError):
        return _client_failure(
            code="invalid_response",
            message="qa.plan.list returned an invalid matching plan row",
            json_mode=parsed.json_mode,
        )

    fetched = call_dispatcher(
        function_id="qa.plan.get",
        target=target,
        payload={"project": project, "plan_id": plan_id},
        actor=actor,
    )
    if not fetched.success:
        return emit_response(fetched, json_mode=parsed.json_mode)
    plan = (fetched.result or {}).get("plan")
    if not isinstance(plan, dict):
        return _client_failure(
            code="invalid_response",
            message="qa.plan.get returned no plan document",
            json_mode=parsed.json_mode,
        )
    try:
        base_updated_at = plan["updated_at"]
        if not isinstance(base_updated_at, str) or not base_updated_at:
            raise ValueError("qa.plan.get returned an invalid updated_at")
        document = _authoring_document(plan)
    except (KeyError, TypeError, ValueError) as exc:
        return _client_failure(
            code="invalid_response",
            message=f"could not prepare the plan editor document: {exc}",
            json_mode=parsed.json_mode,
        )
    try:
        path = _write_document(parsed.slug, document)
    except OSError as exc:
        return _client_failure(
            code="local_io_failed",
            message=f"could not create the plan editor document: {exc}",
            json_mode=parsed.json_mode,
        )

    try:
        editor = _editor_argv(parsed.editor)
        completed = subprocess.run([*editor, str(path)], check=False)
    except KeyboardInterrupt:
        _preserved(path, "editor interrupted")
        raise
    except (OSError, ValueError) as exc:
        return _client_failure(
            code="editor_start_failed",
            message=f"editor could not start: {exc}",
            json_mode=parsed.json_mode,
            preserved_path=path,
        )
    if completed.returncode != 0:
        return _client_failure(
            code="editor_exit_failed",
            message=f"editor exited with status {completed.returncode}",
            json_mode=parsed.json_mode,
            preserved_path=path,
        )
    try:
        document = _load_edited_document(path, parsed.slug)
    except ValueError as exc:
        return _client_failure(
            code="invalid_editor_document",
            message=str(exc),
            json_mode=parsed.json_mode,
            preserved_path=path,
        )

    saved = call_dispatcher(
        function_id="qa.plan.edit",
        target=target,
        payload={
            "project": project,
            "base_updated_at": base_updated_at,
            **document,
        },
        actor=actor,
    )
    if not saved.success:
        _preserved(path, "plan save was refused")
        return emit_response(saved, json_mode=parsed.json_mode)
    try:
        path.unlink()
    except OSError as exc:
        print(
            f"warning: plan saved but temporary document could not be "
            f"removed: {path} ({exc})",
            file=sys.stderr,
        )
    return emit_response(saved, json_mode=parsed.json_mode)


USAGE_BY_FUNCTION_ID = {
    "qa.plan.edit": QA_PLAN_EDIT_USAGE,
}


__all__ = [
    "QA_PLAN_EDIT_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "qa_plan_edit",
]
