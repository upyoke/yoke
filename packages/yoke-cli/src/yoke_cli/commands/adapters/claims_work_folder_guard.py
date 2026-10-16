"""Keep item work in the caller machine's registered project checkout."""

from __future__ import annotations

from pathlib import Path
import sys

from yoke_cli.commands._helpers import ensure_handlers_loaded, item_target
from yoke_cli.config.project_slug_lookup import resolve_project_slug
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
from yoke_contracts.machine_config.runtime import load_config
from yoke_contracts.machine_config.schema_projects import normalize_projects
from yoke_contracts.project_defaults import default_project_for_directory


class FolderGuardError(RuntimeError):
    """A required authority read failed; acquiring work must not continue."""


def local_checkout_for_project(project_id: int) -> str | None:
    for entry in normalize_projects(load_config().get("projects")):
        if entry["project_id"] == project_id:
            return entry["checkout"]
    return None


def render_folder_line(project_id: int, slug: str, ref: str, title: str) -> str:
    checkout = local_checkout_for_project(project_id)
    subject = f"{ref} ({title})"
    if checkout is None:
        return (
            f"No local checkout is mapped to project {slug} for {subject}. "
            f"Recovery: run `yoke project register CHECKOUT --project-id {project_id}`, "
            "then open a session there; sessions never switch projects."
        )
    return (
        f"Open a session in {checkout} (project {slug}) to work on {subject}; "
        "sessions never switch projects."
    )


def _work_item(item_ref: str) -> dict:
    ensure_handlers_loaded()
    response = call_dispatcher(
        function_id="items.get.run",
        target=item_target("item", item_ref, None),
        payload={"fields": ["project_id", "title"]},
        actor=build_actor(),
    )
    if not response.success:
        error = response.error
        raise FolderGuardError(
            f"{error.code}: {error.message}"
            if error
            else "ITEM_LOOKUP_FAILED: authority read failed"
        )
    fields = (response.result or {}).get("fields") or {}
    if (
        not isinstance(fields.get("project_id"), int)
        or not fields.get("title")
        or not (response.result or {}).get("public_ref")
    ):
        raise FolderGuardError(
            "ITEM_IDENTITY_UNAVAILABLE: authority returned incomplete item identity. "
            "Recovery: ask the control-plane operator to restore the item projection."
        )
    return {
        **fields,
        "public_ref": response.result["public_ref"],
    }


def _folder_line(item: dict) -> str:
    return render_folder_line(
        item["project_id"],
        resolve_project_slug(str(item["project_id"])),
        item["public_ref"],
        item["title"],
    )


def check_caller_folder(item_ref: str) -> str | None:
    item = _work_item(item_ref)
    if default_project_for_directory(Path.cwd()) == str(item["project_id"]):
        return None
    return _folder_line(item)


def refuse_caller_folder(item_ref: str) -> bool:
    try:
        line = check_caller_folder(item_ref)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return True
    if line:
        print(f"CLAIM_FOLDER_MISMATCH: {line}", file=sys.stderr)
    return line is not None


def folder_response_recovery(item_ref: str | None):
    def recover(response, actor):
        error = response.error
        if (
            item_ref
            and error
            and error.code
            in {
                "SESSION_MACHINE_SCOPE_WORK_REFUSED",
                "SESSION_PROJECT_MISMATCH",
            }
        ):
            try:
                line = _folder_line(_work_item(item_ref))
            except Exception as exc:
                line = f"Local folder recovery unavailable: {exc}"
            response = response.model_copy(
                update={
                    "error": error.model_copy(
                        update={"message": f"{error.message} {line}"}
                    ),
                }
            )
        return response

    return recover
