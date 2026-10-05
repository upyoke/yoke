"""Client project selection with an authority-scoped missing-project refusal."""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.project_defaults import (
    MissingProjectError,
    default_project_for_directory,
    missing_project_message,
)


def required_project_context(
    project: str | None = None, *, directory: Path | None = None
) -> str:
    import os

    selected = str(project or os.environ.get("YOKE_PROJECT") or "").strip()
    selected = selected or default_project_for_directory(directory or Path.cwd())
    if selected:
        return selected
    from yoke_contracts.api.function_call import TargetRef
    from yoke_cli.commands._helpers import ensure_handlers_loaded
    from yoke_cli.transport.dispatcher import build_actor, call_dispatcher

    try:
        ensure_handlers_loaded()
        response = call_dispatcher(
            function_id="projects.list",
            target=TargetRef(kind="global"),
            payload={"fields": ["id", "slug"]},
            actor=build_actor(),
        )
        if not response.success:
            raise RuntimeError(
                response.error.message if response.error else "roster read failed"
            )
        message = missing_project_message(
            [str(row["slug"]) for row in response.result["rows"]]
        )
    except Exception as exc:  # noqa: BLE001 - report why the roster could not be read
        message = missing_project_message([], unavailable=str(exc))
    raise MissingProjectError(message)
