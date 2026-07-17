"""Write one stack-scoped Pulumi config to an owner-only local file."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
from typing import List

from yoke_cli.commands._helpers import (
    add_session_arg,
    ensure_handlers_loaded,
    parse_or_usage_error,
)
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
from yoke_cli.commands.pulumi_stack_config_loader import (
    load_pulumi_stack_config,
)
from yoke_contracts.api.function_call import TargetRef


PULUMI_STACK_CONFIG_GET_USAGE = (
    "yoke projects pulumi-stack-config get --project NAME --stack STACK "
    "--output FILE [--force]"
)


def projects_pulumi_stack_config_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke projects pulumi-stack-config get",
        description=(
            "Materialize one stack-scoped schema-v2 Pulumi config as a new "
            "owner-only file. The sensitive config body is never emitted."
        ),
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--stack", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--force", action="store_true")
    add_session_arg(parser)
    parsed = parse_or_usage_error(parser, args, PULUMI_STACK_CONFIG_GET_USAGE)
    if parsed is None:
        return 2
    target = parsed.output.expanduser().resolve()
    if target.exists() and not parsed.force:
        return _error(f"output already exists: {target}; pass --force to replace it")
    ensure_handlers_loaded()
    response = call_dispatcher(
        function_id="projects.pulumi_stack_config.get",
        target=TargetRef(kind="global"),
        payload={"project": parsed.project, "stack": parsed.stack},
        actor=build_actor(session_id=parsed.session_id),
    )
    if not response.success:
        message = response.error.message if response.error else "request failed"
        return _error(message, exit_code=1)
    try:
        materialized = load_pulumi_stack_config(parsed.project, parsed.stack)
    except Exception as exc:
        return _error(f"could not materialize stack config: {exc}", exit_code=1)
    payload = json.dumps(
        materialized, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"
    try:
        _write_owner_only(target, payload, force=parsed.force)
    except OSError as exc:
        return _error(f"could not write {target}: {exc}", exit_code=1)
    digest = hashlib.sha256(payload).hexdigest()
    sys.stdout.write(f"{target}|{len(payload)}|{digest}\n")
    return 0


def _write_owner_only(target: Path, payload: bytes, *, force: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(
        f".{target.name}.tmp-{os.getpid()}-{secrets.token_hex(6)}"
    )
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if force:
            os.replace(temporary, target)
        else:
            os.link(temporary, target)
            temporary.unlink()
        target.chmod(0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def _error(message: str, *, exit_code: int = 2) -> int:
    print(json.dumps({"success": False, "message": message}), file=sys.stderr)
    return exit_code


__all__ = [
    "PULUMI_STACK_CONFIG_GET_USAGE",
    "projects_pulumi_stack_config_get",
]
