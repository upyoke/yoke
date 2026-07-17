"""CLI adapter for the typed Pulumi state migration."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


PULUMI_STATE_MIGRATE_USAGE = (
    "yoke projects pulumi-state migrate --project NAME --site-id ID "
    "--stack NAME [--stack NAME ...] [--apply] [--json]"
)
PULUMI_STATE_CHECKPOINT_IMPORT_USAGE = (
    "yoke projects pulumi-state checkpoint-import --project NAME "
    "--stack NAME --checkpoint-file PATH [--apply] [--json]"
)
_MAX_CHECKPOINT_BYTES = 16 * 1024 * 1024


def projects_pulumi_state_migrate(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke projects pulumi-state migrate",
        description=(
            "Move one exact set of Pulumi operator-state entries from a site "
            "to the project capability. Dry-runs by default and never emits "
            "the migrated values."
        ),
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--site-id", required=True)
    parser.add_argument("--stack", dest="stack_names", action="append", required=True)
    parser.add_argument("--apply", action="store_true")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, PULUMI_STATE_MIGRATE_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        del stderr
        result = response.result or {}
        stdout.write(
            f"{result.get('mode', '')}|{result.get('receipt_digest', '')}\n"
        )

    return dispatch_and_emit(
        function_id="projects.pulumi_state.migrate",
        target=TargetRef(kind="global"),
        payload={
            "project": parsed.project,
            "site_id": parsed.site_id,
            "stack_names": parsed.stack_names,
            "apply": parsed.apply,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def projects_pulumi_state_checkpoint_import(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke projects pulumi-state checkpoint-import",
        description=(
            "Register one stack's encrypted operator metadata from an "
            "owner-only Pulumi checkpoint file. Dry-runs by default and "
            "never emits the imported values."
        ),
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--stack", dest="stack_name", required=True)
    parser.add_argument("--checkpoint-file", required=True)
    parser.add_argument("--apply", action="store_true")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, PULUMI_STATE_CHECKPOINT_IMPORT_USAGE
    )
    if parsed is None:
        return 2
    try:
        secrets_provider, encrypted_key = _read_checkpoint_operator_state(
            Path(parsed.checkpoint_file)
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    def _human_writer(response, stdout, stderr) -> None:
        del stderr
        result = response.result or {}
        stdout.write(
            f"{result.get('mode', '')}|{result.get('receipt_digest', '')}\n"
        )

    return dispatch_and_emit(
        function_id="projects.pulumi_state.checkpoint_import",
        target=TargetRef(kind="global"),
        payload={
            "project": parsed.project,
            "stack_name": parsed.stack_name,
            "secrets_provider": secrets_provider,
            "encrypted_key": encrypted_key,
            "apply": parsed.apply,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def _read_checkpoint_operator_state(path: Path) -> tuple[str, str]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("checkpoint must be a regular file")
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError(
                "checkpoint must be owned by the current user with no "
                "group or other access (run chmod 600)"
            )
        if info.st_size <= 0 or info.st_size > _MAX_CHECKPOINT_BYTES:
            raise ValueError("checkpoint file size is outside the safe limit")
        with os.fdopen(fd, "r", encoding="utf-8") as stream:
            fd = -1
            document = json.load(stream)
    except json.JSONDecodeError as exc:
        raise ValueError("checkpoint must contain valid JSON") from exc
    finally:
        if fd >= 0:
            os.close(fd)
    try:
        deployment = document.get("deployment")
        if deployment is None:
            deployment = document["checkpoint"]["latest"]
        state = deployment["secrets_providers"]["state"]
        secrets_provider = state["url"]
        encrypted_key = state["encryptedkey"]
    except (KeyError, TypeError) as exc:
        raise ValueError(
            "checkpoint does not contain Pulumi secrets-provider state"
        ) from exc
    if not isinstance(secrets_provider, str) or not secrets_provider.strip():
        raise ValueError("checkpoint secrets-provider URL is invalid")
    if not isinstance(encrypted_key, str) or not encrypted_key.strip():
        raise ValueError("checkpoint encrypted key is invalid")
    return secrets_provider.strip(), encrypted_key.strip()


__all__ = [
    "PULUMI_STATE_CHECKPOINT_IMPORT_USAGE",
    "PULUMI_STATE_MIGRATE_USAGE",
    "projects_pulumi_state_checkpoint_import",
    "projects_pulumi_state_migrate",
]
