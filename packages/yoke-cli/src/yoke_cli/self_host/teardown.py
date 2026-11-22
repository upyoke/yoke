"""Take a self-host bundle back off a machine, leaving nothing that lies.

A stopped stack is not a removed one. What survived ``docker compose down -v``
before this command existed was roughly a gigabyte of pulled images, a bundle
directory full of live-looking secrets including the admin token file, and a
machine config whose active authority pointed at a server that no longer
answers — none of it reachable through any Yoke command, so the only way out
was editing ``~/.yoke/config.json`` by hand.

The database volume is the universe itself, so removal takes its own flag
and consent.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Sequence

from yoke_cli.self_host import atomic_file, bundle, env_file
from yoke_contracts.onboard_destinations import is_hosted_url
from yoke_contracts.self_host_bootstrap_output import connect_url_from_publish_spec

_RUN = subprocess.run
_WHICH = shutil.which

#: Bundle files this command may delete. Anything else in the directory is the
#: operator's, so teardown reports it rather than removing it.
_OWNED_FILE_NAMES = (
    bundle.COMPOSE_FILE_NAME,
    bundle.ENV_FILE_NAME,
    bundle.GITIGNORE_FILE_NAME,
)


class SelfHostTeardownError(RuntimeError):
    """The teardown cannot proceed; the message names what to do instead."""


def tear_down(
    *,
    directory: str | None = None,
    destroy_universe: bool = False,
    remove_images: bool = False,
    remove_bundle: bool = False,
    keep_connection: bool = False,
    activate: str | None = None,
    config_path: str | None = None,
    remove_connections: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Retire dead authorities, then remove exactly what the caller asked for."""
    target = Path(directory) if directory else bundle.default_bundle_dir()
    target = target.expanduser().resolve()
    if not (target / bundle.COMPOSE_FILE_NAME).is_file():
        raise SelfHostTeardownError(
            f"no self-host bundle at {target}: it has no "
            f"{bundle.COMPOSE_FILE_NAME}. Name the bundle with --dir PATH"
        )
    if keep_connection and activate is not None:
        raise SelfHostTeardownError(
            "--keep-connection leaves authority unchanged, so it cannot be "
            "combined with --activate; choose one and re-run"
        )
    docker = _require_docker()
    images = _bundle_images(docker, target) if remove_images else ()
    connection_report = None
    connections_left: list[dict[str, str]] = []
    machine_locks_removed: list[str] = []
    relays_removed: list[str] = []
    projects_uninstalled: list[str] = []
    if not keep_connection:
        connection_report, connections_left, relays_removed, projects_uninstalled = _retire_connections(
            target,
            activate=activate,
            config_path=config_path,
            remove=remove_connections,
        )
        if connection_report is not None:
            machine_locks_removed = _remove_machine_lock_files(config_path)
    try:
        _compose(
            docker,
            target,
            ("down", "-v") if destroy_universe else ("down",),
        )
    except SelfHostTeardownError as exc:
        removed = (connection_report or {}).get("removed_envs") or []
        if removed:
            raise SelfHostTeardownError(
                f"{exc} Connections {removed} were retired before Docker "
                "teardown so none can point at a partially stopped server; "
                "the bundle credential remains. Fix Docker and re-run teardown"
            ) from exc
        raise
    report: dict[str, Any] = {
        "ok": True,
        "directory": str(target),
        "universe_destroyed": bool(destroy_universe),
        "images_removed": [],
        "images_retained": [],
        "bundle_files_removed": [],
        "bundle_files_retained": [],
        "connection": connection_report,
        "connections_left": connections_left,
        "machine_locks_removed": machine_locks_removed,
        "relays_removed": relays_removed,
        "projects_uninstalled": projects_uninstalled,
        "machine_uninstall": [],
    }
    for image in images:
        removed = _remove_image(docker, target, image)
        report["images_removed" if removed else "images_retained"].append(image)
    if not keep_connection:
        from yoke_contracts.machine_config import reader as machine_config
        from yoke_cli.self_host.teardown_installation import finish_machine

        try:
            report["machine_uninstall"] = finish_machine(
                machine_config.config_path(config_path).absolute(), target
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise SelfHostTeardownError(
                f"Stack removed, but machine uninstall failed: {exc}. "
                "Repair the reported step and retry self-host teardown."
            ) from exc
    if remove_bundle:
        _remove_bundle_files(target, report)
    return report


def bundle_connect_url(target: Path | str) -> str:
    """The URL a client would have been connected to for this bundle."""
    return connect_url_from_publish_spec(env_file.read_publish_spec(target))


def _require_docker() -> str:
    executable = _WHICH("docker")
    if not executable:
        raise SelfHostTeardownError(
            "docker is required to stop and remove the self-host stack; "
            "install it, or remove the bundle directory by hand once the "
            "containers are gone"
        )
    return executable


def _compose(executable: str, target: Path, args: Sequence[str]) -> str:
    result = _run(executable, target, ("compose", *args), timeout=180.0)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-2048:]
        raise SelfHostTeardownError(
            f"`docker compose {' '.join(args)}` failed in {target}: {detail}. "
            "No later teardown step ran; fix the reported problem and re-run"
        )
    return result.stdout or ""


def _bundle_images(executable: str, target: Path) -> tuple[str, ...]:
    """Ask Compose which images this bundle uses, before it is torn down."""
    listing = _compose(executable, target, ("config", "--images"))
    return tuple(
        dict.fromkeys(line.strip() for line in listing.splitlines() if line.strip())
    )


def _remove_image(executable: str, target: Path, image: str) -> bool:
    """Remove one image, leaving it alone when something else still uses it."""
    result = _run(executable, target, ("image", "rm", image), timeout=120.0)
    return result.returncode == 0


def _remove_bundle_files(target: Path, report: dict[str, Any]) -> None:
    """Delete the files the bundle writer owns, and nothing else.

    Each protected file carries a sibling advisory lock the atomic writer
    created; leaving those behind is what keeps an otherwise emptied
    ``secrets/`` directory alive.
    """
    secrets_dir = target / bundle.SECRETS_DIR_NAME
    written = [
        *(secrets_dir / name for name in bundle.BUNDLE_SECRET_NAMES),
        *(target / name for name in _OWNED_FILE_NAMES),
    ]
    owned = [
        path
        for written_path in written
        for path in (written_path, atomic_file.target_lock_path(written_path))
    ]
    for path in owned:
        if path.is_file() or path.is_symlink():
            path.unlink()
            report["bundle_files_removed"].append(str(path))
    for directory in (secrets_dir, target):
        remaining = (
            sorted(p.name for p in directory.iterdir()) if directory.is_dir() else []
        )
        if not remaining:
            directory.rmdir()
        else:
            report["bundle_files_retained"].extend(
                str(directory / name) for name in remaining
            )
            break


def _bundle_connections(
    target: Path, connections: dict[str, Any]
) -> tuple[list[str], list[dict[str, str]]]:
    """Match the published URL or prove that the bundle issued the alias's token."""
    url = bundle_connect_url(target)
    selected: list[str] = []
    left: list[dict[str, str]] = []
    for name, entry in sorted(connections.items()):
        if not isinstance(entry, dict):
            continue
        api_url = str(entry.get("api_url") or "").rstrip("/")
        if api_url == url:
            selected.append(str(name))
        elif entry.get("transport") == "https" and not is_hosted_url(api_url):
            refusal = _identity_refusal(url, entry)
            if refusal is None:
                selected.append(str(name))
            else:
                left.append({"env": str(name), "api_url": api_url, "reason": refusal})
    return selected, left


def _retire_connections(
    target: Path,
    *,
    activate: str | None,
    config_path: str | None,
    remove: Callable[..., dict[str, Any]] | None,
) -> tuple[dict[str, Any] | None, list[dict[str, str]], list[str], list[str]]:
    from yoke_contracts.machine_config import reader as machine_config
    from yoke_cli.config import writer
    from yoke_cli.config.writer_connection_remove import resolve_active_authority
    from yoke_cli.self_host.teardown_installation import remove_layers

    config = machine_config.config_path(config_path).absolute()
    payload = machine_config.load_config(config)
    entries = payload.get("connections")
    connections = entries if isinstance(entries, dict) else {}
    selected, left = _bundle_connections(target, connections)
    if not selected:
        if activate is not None:
            raise SelfHostTeardownError(
                f"--activate {activate} has no effect because no machine "
                f"connection reaches {bundle_connect_url(target)}; omit --activate and re-run"
            )
        return None, left, [], []
    try:
        resolve_active_authority(
            dict(payload), envs=set(selected), activate=activate, connections=connections
        )
        relays, projects = remove_layers(selected, payload, config)
        retired = (remove or writer.remove_connections)(
            selected, activate=activate, path=config
        )
        return retired, left, relays, projects
    except Exception as exc:  # noqa: BLE001 - reported as a teardown refusal
        raise SelfHostTeardownError(
            f"teardown refused before stopping the stack: {exc}. "
            "Repair the reported step and retry self-host teardown"
        ) from exc


def _identity_refusal(url: str, entry: dict[str, Any]) -> str | None:
    """Why ``entry``'s own token proves no identity at ``url``; None if it does."""
    from yoke_cli.config import server_connect
    from yoke_cli.transport.https_credentials import TransportError, resolve_token

    try:
        server_connect.verify_server_identity(url, token=resolve_token(entry))
    except (
        TransportError,
        server_connect.ServerConnectError,
        server_connect.ServerIdentityError,
    ) as exc:
        return str(exc)
    return None


def _remove_machine_lock_files(config_path: str | None) -> list[str]:
    """Remove the idle lock artifacts created by connection retirement."""
    from yoke_cli.config import (
        github_git_credential_file,
        github_machine_operation,
        machine_config_file,
    )
    from yoke_contracts.machine_config import reader as machine_config

    targets = (
        machine_config_file.config_lock_path(machine_config.config_path(config_path)),
        github_git_credential_file.lock_path(
            github_machine_operation.operation_lock_target()
        ),
    )
    removed: list[str] = []
    try:
        for target in targets:
            if machine_config_file.remove_idle_lock_file(target):
                removed.append(str(target))
    except machine_config_file.MachineConfigFileError as exc:
        raise SelfHostTeardownError(str(exc)) from exc
    return removed


def _run(
    executable: str,
    target: Path,
    args: Sequence[str],
    *,
    timeout: float,
) -> subprocess.CompletedProcess[str]:
    try:
        return _RUN(
            (executable, *args),
            cwd=target,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SelfHostTeardownError(
            f"`docker {' '.join(args)}` could not complete in {target}: {exc}"
        ) from exc


__all__ = [
    "SelfHostTeardownError",
    "bundle_connect_url",
    "tear_down",
]
