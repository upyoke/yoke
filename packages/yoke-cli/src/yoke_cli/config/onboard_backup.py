"""Backup validation and restore using the existing product commands."""

from __future__ import annotations

import getpass
import json
import os
import subprocess
import sys
from pathlib import Path

from yoke_contracts.self_host_bootstrap_output import redact_api_tokens
from yoke_cli.config import machine_config, existing_project_lookup
from yoke_cli.config import onboard_self_host_server as server
from yoke_cli.self_host import runtime
from yoke_contracts import terminal_detached_process


class BackupSetupError(RuntimeError):
    """A diagnosed refusal safe to show without exposing credentials."""


def command(
    config_path: str, *args: str, timeout: float = 600, json_output: bool = True
) -> dict:
    environment = dict(os.environ)
    environment[machine_config.CONFIG_FILE_ENV] = config_path
    for key in ("YOKE_SESSION_ID", "YOKE_ACTOR_ID"):
        environment.pop(key, None)
    try:
        result = terminal_detached_process.run(
            [
                sys.executable,
                "-m",
                "yoke_cli.main",
                *args,
                *(["--json"] if json_output else []),
            ],
            env=environment,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BackupSetupError(
            "backup_command_unavailable: the backup operation could not finish; "
            "check the destination and retry this step."
        ) from exc
    if result.returncode:
        reason = redact_api_tokens(result.stderr.strip())
        raise BackupSetupError(
            f"backup_command_failed: {reason}; correct the named problem and retry."
        )
    if not json_output:
        return {}
    try:
        payload = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise BackupSetupError(
            "backup_receipt_unreadable: no readable receipt; inspect the "
            "destination before retrying the import."
        ) from exc
    if not isinstance(payload, dict):
        raise BackupSetupError(
            "backup_receipt_invalid: expected an object; inspect the destination "
            "before retrying the import."
        )
    if payload.get("success") is False or payload.get("ok") is False:
        raise BackupSetupError(
            "backup_operation_refused: "
            + redact_api_tokens(str(payload.get("error")))
            + "; correct the named problem and retry."
        )
    return payload


def validate(config_path: str, value: str) -> dict:
    archive = Path(value).expanduser().resolve()
    report = command(config_path, "universe", "validate", str(archive))
    if report.get("ok") is not True or not report.get("receipt_verified"):
        raise BackupSetupError(
            "backup_validation_incomplete: no verified freeze receipt; choose a "
            "backup from uninstall with backup or the web export panel."
        )
    return report


def restore_local(shell, archive: str) -> None:
    if not getattr(shell, "_backup_local_imported", False):
        command(
            shell.result.config_path,
            "init",
            "--local",
            "--admin-name",
            getpass.getuser(),
            "--config",
            shell.result.config_path,
        )
        receipt = _import(
            shell,
            shell.result.config_path,
            "--env",
            "local",
            "universe",
            "import",
            archive,
            "--yes",
        )
        shell._backup_local_imported = True
        shell._backup_owner_id = receipt.get("actor_id")
        if not isinstance(shell._backup_owner_id, int) or shell._backup_owner_id <= 0:
            shell._backup_import_uncertain = True
            raise BackupSetupError(
                "backup_owner_missing: restore returned no local owner; inspect "
                "the restored actors and bind the intended actor before continuing."
            )
    command(
        shell.result.config_path,
        "--env",
        "local",
        "config",
        "bind-actor",
        "--actor-id",
        str(shell._backup_owner_id),
        "--config",
        shell.result.config_path,
        json_output=False,
    )
    shell.result.admin_name = None


def restore_server(shell, setup, archive: str) -> None:
    prerequisites = server.check_docker_prerequisites()
    if not setup.raw_token:
        # This bootstrap identity is replaced before core first boot.
        setup.admin_name = getpass.getuser()
        server._ensure_wizard_bundle(setup)
        receipt = _import(
            shell,
            shell.result.config_path,
            "self-host",
            "import",
            archive,
            "--dir",
            str(setup.directory),
            "--yes",
        )
        raw_token = receipt.get("raw_token")
        if not isinstance(raw_token, str) or not raw_token:
            shell._backup_import_uncertain = True
            raise BackupSetupError(
                "backup_credential_missing: no admin credential; run yoke "
                "self-host import --recover-credential for this bundle."
            )
        setup.raw_token = raw_token
    runtime.start_bundle(directory=setup.directory, executable=prerequisites.executable)
    server.retry_connection(setup)
    from yoke_cli.config.onboard_wizard_self_host import _select_connection

    _select_connection(shell, setup)


def _import(shell, config_path, *args):
    if getattr(shell, "_backup_import_uncertain", False):
        raise BackupSetupError(
            "backup_import_outcome_unknown: inspect the destination and recover "
            "its credential or actor binding, then restart setup. Import will "
            "not be repeated without a known outcome."
        )
    try:
        return command(config_path, *args)
    except BackupSetupError as exc:
        if any(
            code in str(exc)
            for code in (
                "backup_command_unavailable",
                "backup_receipt_unreadable",
                "backup_receipt_invalid",
            )
        ):
            shell._backup_import_uncertain = True
        raise


def projects(shell) -> list[dict]:
    from yoke_cli.config.onboard_destinations import DESTINATION_LOCAL

    if shell.result.destination == DESTINATION_LOCAL:
        payload = existing_project_lookup._call_local_function(
            config_path=shell.result.config_path,
            function="projects.list",
            payload={},
        )
    else:
        payload = existing_project_lookup._call_function(
            api_url=shell.result.api_url,
            token=shell._yoke_token_for_project_lookup(),
            function="projects.list",
            payload={},
        )
    result = payload.get("result")
    rows = result.get("rows") if isinstance(result, dict) else None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise BackupSetupError(
            "backup_projects_unreadable: project list unavailable; check this "
            "universe's connection and retry."
        )
    return rows
