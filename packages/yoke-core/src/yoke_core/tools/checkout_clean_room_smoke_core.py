"""Core flow for the checkout clean-room smoke."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping

from yoke_core.tools.checkout_clean_room_smoke_helpers import (
    SMOKE_EVENT_NAME,
    SMOKE_EVENT_TYPE,
    CommandResult,
    SmokeError,
    assert_clean_clone_shape,
    assert_event_visible,
    assert_status_clean_room,
    base_env,
    direct_python_probe,
    isolated_env,
    run,
    run_json,
)


def run_smoke(
    *,
    source_root: Path,
    dsn_file: Path,
    env_name: str,
    project_id: int,
    python: Path,
    work_dir: Path | None,
    keep_work_dir: bool,
) -> dict[str, Any]:
    source_root = source_root.resolve()
    dsn_file = dsn_file.resolve()
    if not dsn_file.is_file():
        raise SmokeError(f"DSN file is missing: {dsn_file}")
    if project_id <= 0:
        raise SmokeError("--project-id must be positive")

    root = work_dir or Path(tempfile.mkdtemp(prefix="yoke-checkout-smoke-"))
    root.mkdir(parents=True, exist_ok=True)
    clone = root / "clone"
    venv_dir = root / "venv"
    home = root / "home"
    machine_home = home / ".yoke"
    secrets_dir = machine_home / "secrets"
    config_path = machine_home / "config.json"
    copied_dsn = secrets_dir / "authority.dsn"
    temp_root = machine_home / "tmp"
    cache_dir = machine_home / "cache"
    session_id = "checkout-clean-room-smoke"
    commands: list[CommandResult] = []

    try:
        run(
            ["git", "clone", "--quiet", "--no-local", str(source_root), str(clone)],
            step="clone",
            cwd=root,
            commands=commands,
            env=base_env(home),
        )
        assert_clean_clone_shape(clone)
        run(
            [str(python), "-m", "venv", str(venv_dir)],
            step="create-venv",
            cwd=clone,
            commands=commands,
            env=base_env(home),
        )
        py = venv_dir / "bin" / "python"
        yoke = venv_dir / "bin" / "yoke"
        run(
            [str(py), "-m", "pip", "install", "--upgrade", "pip"],
            step="pip-upgrade",
            cwd=clone,
            commands=commands,
            env=base_env(home),
        )
        run(
            [str(py), "-m", "pip", "install", "-e", "."],
            step="editable-install",
            cwd=clone,
            commands=commands,
            env=base_env(home),
        )

        env = isolated_env(
            home=home,
            machine_home=machine_home,
            config_path=config_path,
            venv_bin=venv_dir / "bin",
            env_name=env_name,
            session_id=session_id,
        )
        example = run(
            [str(yoke), "config", "example"],
            step="config-example",
            cwd=clone,
            commands=commands,
            env=env,
        )
        payload = build_machine_config(
            example_payload=json.loads(example.stdout),
            clone_root=clone,
            copied_dsn=copied_dsn,
            temp_root=temp_root,
            cache_dir=cache_dir,
            env_name=env_name,
            project_id=project_id,
        )
        _write_machine_files(
            machine_home=machine_home,
            secrets_dir=secrets_dir,
            config_path=config_path,
            copied_dsn=copied_dsn,
            source_dsn=dsn_file,
            payload=payload,
        )

        status = run_json(
            [str(yoke), "status", "--config", str(config_path),
             "--repo-root", str(clone), "--json"],
            step="yoke-status",
            cwd=clone,
            commands=commands,
            env=env,
        )
        assert_status_clean_room(status, clone=clone, yoke=yoke)
        direct = run_json(
            [str(py), "-c", direct_python_probe()],
            step="direct-python-read-write",
            cwd=clone,
            commands=commands,
            env={**env, "SMOKE_PROJECT_ID": str(project_id),
                 "SMOKE_EVENT_NAME": SMOKE_EVENT_NAME,
                 "SMOKE_EVENT_TYPE": SMOKE_EVENT_TYPE},
        )
        if not direct.get("write_ok"):
            raise SmokeError(
                "direct Python event write did not report success: "
                f"{direct.get('write_reason') or '<no reason>'}"
            )
        return _cli_readback_report(
            clone=clone,
            root=root,
            source_root=source_root,
            config_path=config_path,
            copied_dsn=copied_dsn,
            yoke=yoke,
            py=py,
            env=env,
            commands=commands,
            status=status,
            direct=direct,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise SmokeError(str(exc)) from exc
    finally:
        if not keep_work_dir and work_dir is None:
            shutil.rmtree(root, ignore_errors=True)


def build_machine_config(
    *,
    example_payload: Mapping[str, Any],
    clone_root: Path,
    copied_dsn: Path,
    temp_root: Path,
    cache_dir: Path,
    env_name: str,
    project_id: int,
) -> dict[str, Any]:
    payload = dict(example_payload)
    connections = payload.get("connections")
    base = (dict(connections.get(env_name) or {})
            if isinstance(connections, Mapping) else {})
    base.update({
        "transport": "local-postgres",
        "credential_source": {"kind": "dsn_file", "path": str(copied_dsn)},
    })
    payload["active_env"] = env_name
    payload["connections"] = {env_name: base}
    payload["temp_root"] = str(temp_root)
    payload["cache_dir"] = str(cache_dir)
    payload["projects"] = [
        {
            "checkout": str(clone_root.resolve()),
            "project_id": project_id,
            "env": env_name,
            "board": {"render_path": ".yoke/BOARD.md", "scope": str(project_id)},
        }
    ]
    payload.setdefault("settings", {})
    return payload


def _write_machine_files(
    *,
    machine_home: Path,
    secrets_dir: Path,
    config_path: Path,
    copied_dsn: Path,
    source_dsn: Path,
    payload: Mapping[str, Any],
) -> None:
    machine_home.mkdir(parents=True, exist_ok=True)
    secrets_dir.mkdir(parents=True, exist_ok=True)
    copied_dsn.write_text(
        source_dsn.read_text(encoding="utf-8").strip() + "\n",
        encoding="utf-8",
    )
    copied_dsn.chmod(0o600)
    (machine_home / "tmp").mkdir(parents=True, exist_ok=True)
    (machine_home / "cache").mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    config_path.chmod(0o600)


def _cli_readback_report(
    *,
    clone: Path,
    root: Path,
    source_root: Path,
    config_path: Path,
    copied_dsn: Path,
    yoke: Path,
    py: Path,
    env: Mapping[str, str],
    commands: list[CommandResult],
    status: Mapping[str, Any],
    direct: Mapping[str, Any],
) -> dict[str, Any]:
    item_ref = str(direct["item_ref"])
    item_get = run_json(
        [str(yoke), "items", "get", item_ref, "title", "--json"],
        step="yoke-items-get",
        cwd=clone,
        commands=commands,
        env=env,
    )
    if not item_get.get("success"):
        raise SmokeError("yoke items get failed in clean clone")
    event_query = run_json(
        [str(yoke), "events", "query", "--event-name", SMOKE_EVENT_NAME,
         "--limit", "1", "--json"],
        step="yoke-events-query",
        cwd=clone,
        commands=commands,
        env=env,
    )
    assert_event_visible(event_query, expected_event_id=str(direct["event_id"]))
    return {
        "ok": True,
        "event_name": SMOKE_EVENT_NAME,
        "event_id": direct["event_id"],
        "item_ref": item_ref,
        "source_root": str(source_root),
        "clone_root": str(clone),
        "work_dir": str(root),
        "config_path": str(config_path),
        "copied_dsn_file": str(copied_dsn),
        "yoke_executable": str(yoke),
        "python_executable": str(py),
        "status": {
            "runtime_import_origin": status["runtime"]["runtime_import_origin"],
            "yoke_executable": status["runtime"]["yoke_executable"],
            "db_action": status["db"]["action"],
            "project_id": status["project"]["project_id"],
            "ambient_env": status["ambient_env"],
        },
        "commands": [result.summary() for result in commands],
    }
