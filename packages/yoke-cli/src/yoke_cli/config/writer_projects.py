"""Machine-local checkout->project-id mapping writers.

Split from :mod:`yoke_cli.config.writer` under the authored-file line cap;
re-exported there so existing imports are unaffected.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional

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

    Re-pointing an already-claimed ``(env, project_id)`` slot at a different
    checkout moves shared routing every other reader resolves against —
    worktree preparation included — so it requires ``reassign=True`` from an
    explicit setup/operator-authorized caller (``yoke onboard``, ``yoke
    project install``/``create``/``import``). Registering a slot with no
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
    env = _registration_env(payload)
    displaced = contract.existing_checkout_for_slot(
        payload.get("projects"), checkout=str(root), project_id=normalized, env=env,
    )
    if displaced is not None and not reassign:
        raise MachineConfigWriteError(
            f"project {normalized} in env {env!r} is already routed to "
            f"{displaced!r}; registering {root} would move shared checkout "
            "routing out from under every other reader (worktree "
            "preparation included). Pass --reassign only for a deliberate "
            "setup/operator-authorized move (yoke onboard, yoke project "
            "install/create/import) — routine agent execution must not "
            "silently repoint an existing project's checkout."
        )
    # Project ids are per universe, so the mapping records the id per env: the
    # (checkout, env) row is upserted, leaving the checkout's rows for other
    # envs intact.
    payload["projects"] = contract.upsert_project_entry(
        payload.get("projects"),
        checkout=str(root),
        project_id=normalized,
        env=env,
        board=None,
    )
    _write_payload(payload, cfg_path)
    written = next(
        (
            e
            for e in payload["projects"]
            if e.get("checkout") == str(root) and e.get("env") == env
        ),
        {},
    )
    return {"checkout": str(root), "entry": written, "config": str(cfg_path)}


@_serialized_mutation
def stamp_untagged_project_envs(
    env: str | None = None,
    *,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Stamp ``env`` onto every untagged ``projects`` entry; log each stamp.

    The creating env cannot be recovered from an untagged legacy entry, so
    the operator chooses one via ``--env`` (default: the machine's current
    ``active_env``). Already-tagged entries are left untouched. Normalizes a
    legacy checkout-keyed object into the canonical flat list. The full
    stamped payload is validated before it is written, so a bogus env is
    refused rather than landing an invalid config.
    """
    payload, cfg_path = _load_payload(path)
    env = env if _nonempty(env) else _registration_env(payload)
    connections = payload.get("connections")
    labels = set(connections) if isinstance(connections, dict) else set()
    if env not in labels:
        raise MachineConfigWriteError(
            f"env {env!r} has no entry in connections (configured: "
            f"{sorted(labels)}); pass a configured env via --env or add one "
            "first with `yoke connection set ENV --transport ...`"
        )
    entries = contract.normalize_projects(payload.get("projects"))
    stamped: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for entry in entries:
        if _nonempty(entry.get("env")):
            skipped.append({"checkout": entry["checkout"], "env": entry["env"]})
            continue
        entry["env"] = env
        stamped.append(
            {
                "checkout": entry["checkout"],
                "env": env,
                "project_id": entry["project_id"],
            }
        )
    payload["projects"] = entries
    _write_payload(payload, cfg_path)
    return {"env": env, "stamped": stamped, "skipped": skipped, "config": str(cfg_path)}


def _registration_env(payload: Mapping[str, Any]) -> str:
    """Resolve the connection env a project mapping is being written under."""
    try:
        return contract.selected_env(payload)
    except contract.MachineConfigContractError as exc:
        raise MachineConfigWriteError(
            "cannot record a project mapping without a resolvable connection "
            "env; add one first with `yoke connection set ENV --transport ...`"
        ) from exc


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


__all__ = ["register_project", "stamp_untagged_project_envs"]
