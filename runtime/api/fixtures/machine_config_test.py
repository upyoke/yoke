"""Test helpers for machine-local checkout mappings."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from yoke_contracts.machine_config import schema as contract


def register_machine_checkout(
    config_root: Path,
    checkout: Path,
    project_id: int,
    *,
    create_checkout: bool = True,
) -> Path:
    """Register *checkout* for *project_id* in a temp machine config.

    ``config_root`` MUST be an absolute per-test temp dir, NOT inside a real git
    working tree. This helper writes ``config_root/yoke-machine-config.json``
    directly — it does not route through ``machine_config.config_path()`` (which
    anchors relative paths under the machine home). A relative config_root would
    write relative to the process cwd, and a repo-derived one (e.g.
    ``repo_root.parent`` when ``repo_root`` is the live checkout) writes into the
    real ``.worktrees/`` tree — both drop stray ``yoke-machine-config.json``
    files into whatever checkout the tests run from. Fail fast on both.
    """

    config_root = Path(config_root)
    if not config_root.is_absolute():
        raise ValueError(
            "register_machine_checkout requires an absolute config_root "
            f"(e.g. tmp_path / 'machine-config'); got {config_root!r}, which "
            "would write yoke-machine-config.json relative to the process cwd"
        )
    # The temp config must live under a throwaway temp root — pytest's tmp_path
    # (under $TMPDIR / gettempdir), or an explicit /tmp the merge tests use —
    # never in the source tree. A repo-derived config_root (e.g. the live
    # checkout's repo_root.parent) drops stray yoke-machine-config.json files
    # into the real .worktrees/. gettempdir() is macOS-specific ($TMPDIR under
    # /var/folders), so /tmp and /var/tmp are listed explicitly.
    temp_bases: list[Path] = []
    for candidate in (
        tempfile.gettempdir(), os.environ.get("TMPDIR"), "/tmp", "/var/tmp",
    ):
        if candidate:
            try:
                temp_bases.append(Path(candidate).resolve())
            except OSError:
                pass
    resolved = config_root.resolve()
    if not any(resolved == base or base in resolved.parents for base in temp_bases):
        raise ValueError(
            f"register_machine_checkout config_root {config_root} is not under a "
            f"temp root ({', '.join(str(b) for b in temp_bases)}); pass a "
            "tmp_path-based dir so the temp machine config never lands in a real "
            "checkout"
        )
    config_root.mkdir(parents=True, exist_ok=True)
    if create_checkout:
        checkout.mkdir(parents=True, exist_ok=True)
    config_path = config_root / "yoke-machine-config.json"
    if config_path.is_file():
        payload: dict[str, Any] = json.loads(config_path.read_text())
    else:
        payload = {}
    payload["projects"] = contract.upsert_project_entry(
        payload.get("projects"),
        checkout=str(checkout),
        project_id=int(project_id),
    )
    config_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    os.environ["YOKE_MACHINE_CONFIG_FILE"] = str(config_path)
    return config_path


def clear_machine_checkout(project_id: int) -> None:
    """Remove any temp machine-config checkout mapping for *project_id*.

    Also unsets ``YOKE_MACHINE_CONFIG_FILE``, which ``register_machine_checkout``
    set directly on ``os.environ`` — so the pointer does not leak into later
    tests/operations in the same worker process.
    """

    raw_path = os.environ.get("YOKE_MACHINE_CONFIG_FILE")
    if not raw_path:
        return
    config_path = Path(raw_path)
    if config_path.is_file():
        payload: dict[str, Any] = json.loads(config_path.read_text())
        entries = contract.normalize_projects(payload.get("projects"))
        payload["projects"] = [
            entry for entry in entries
            if entry["project_id"] != int(project_id)
        ]
        config_path.write_text(
            json.dumps(payload, sort_keys=True), encoding="utf-8"
        )
    os.environ.pop("YOKE_MACHINE_CONFIG_FILE", None)
