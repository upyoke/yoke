"""Machine-local checkout->project-id mapping writers.

Split from :mod:`yoke_cli.config.writer` under the authored-file line cap;
re-exported there so existing imports are unaffected.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from yoke_cli.config.machine_config_mutation import (
    MachineConfigWriteError as MachineConfigWriteError,
    load_payload as _load_payload,
    serialized_mutation as _serialized_mutation,
    write_payload as _write_payload,
)
from yoke_contracts.machine_config import schema as contract


@_serialized_mutation
def register_project(
    repo_root: str | Path,
    project_id: int,
    *,
    board_scope: Optional[str] = None,
    board_render_path: Optional[str] = None,
    reassign: bool = False,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Map a local checkout path to its DB project id.

    Re-pointing an already-claimed ``project_id`` slot at a different
    checkout moves shared routing every other reader resolves against —
    worktree preparation included — so it requires ``reassign=True`` from an
    operator using ``yoke project register --reassign``. Registering a slot with no
    existing checkout, or re-registering the same checkout, is ordinary
    first-time setup and always proceeds without it.
    """
    if board_scope is not None or board_render_path is not None:
        raise MachineConfigWriteError(
            "projects[].board is retired; set board scope under "
            "project-policy.settings.board in the DB"
        )
    root = Path(repo_root).expanduser()
    try:
        root = root.resolve()
    except OSError:
        pass
    if not root.is_dir():
        raise MachineConfigWriteError(f"checkout path is not a directory: {root}")
    normalized = contract.normalize_project_id(project_id)
    if normalized is None:
        raise MachineConfigWriteError("--project-id must be a positive integer")
    payload, cfg_path = _load_payload(path)
    from yoke_contracts.machine_config.project_mapping_upgrade import (
        import_project_connections,
    )

    try:
        import_project_connections(payload)
        connection = contract.project_connection(payload)
        projects = contract.projects_for_connection(payload)
    except contract.MachineConfigContractError as exc:
        raise MachineConfigWriteError(str(exc)) from exc
    displaced = contract.existing_checkout_for_slot(
        projects,
        checkout=str(root),
        project_id=normalized,
    )
    if displaced is not None and not reassign:
        raise MachineConfigWriteError(
            f"project {normalized} is already routed to "
            f"{displaced!r}; registering {root} would move shared checkout "
            "routing. To move it deliberately, run yoke project register "
            "--reassign from a session holding the project's steering seat "
            f"(yoke claims steering acquire --project {normalized})."
        )
    payload["connection_projects"][connection] = contract.upsert_project_entry(
        projects,
        checkout=str(root),
        project_id=normalized,
    )
    _write_payload(payload, cfg_path)
    written = next(
        (
            e
            for e in payload["connection_projects"][connection]
            if e.get("checkout") == str(root)
        ),
        {},
    )
    return {
        "connection": connection,
        "checkout": str(root),
        "entry": written,
        "config": str(cfg_path),
    }


__all__ = ["register_project"]
