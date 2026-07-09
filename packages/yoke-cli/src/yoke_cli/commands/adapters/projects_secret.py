"""``yoke projects capability secret set`` adapter."""

from __future__ import annotations

import argparse
import importlib
import sys
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    ensure_handlers_loaded,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.config import secrets as machine_secrets
from yoke_cli.transport.dispatcher import (
    build_actor,
    call_dispatcher,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.machine_config.capability_secrets import (
    is_machine_local_capability_secret,
)

PROJECTS_CAPABILITY_SECRET_SET_USAGE = (
    "yoke projects capability secret set --project NAME --cap-type TYPE "
    "--key KEY [VALUE | --value-file PATH | --value-stdin] "
    "[--session-id S] [--json]"
)


def projects_capability_secret_set(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke projects capability secret set",
        description=(
            "Store a project capability secret. GitHub App private keys use "
            "the app_private_key secret while repository access uses binding "
            "rows; aws-admin secrets and ssh.private_key are stored on this "
            "machine under ~/.yoke/secrets. VALUE is the default input; "
            "--value-file and --value-stdin import the secret value without "
            "printing it."
        ),
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--cap-type", dest="cap_type", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("value", nargs="?")
    parser.add_argument("--value-file", dest="value_file", default=None)
    parser.add_argument("--value-stdin", dest="value_stdin", action="store_true")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, PROJECTS_CAPABILITY_SECRET_SET_USAGE,
    )
    if parsed is None:
        return 2
    sources = [bool(parsed.value), bool(parsed.value_file), parsed.value_stdin]
    if sum(1 for source in sources if source) != 1:
        return usage_error(
            "exactly one secret value source is required: "
            f"{PROJECTS_CAPABILITY_SECRET_SET_USAGE}"
        )
    try:
        value = _project_secret_value(parsed)
    except machine_secrets.MachineSecretError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if is_machine_local_capability_secret(parsed.cap_type, parsed.key):
        return _store_machine_local_secret(parsed, value)

    return dispatch_and_emit(
        function_id="projects.capability_secret.set",
        target=TargetRef(kind="global"),
        payload={
            "project": parsed.project,
            "cap_type": parsed.cap_type,
            "key": parsed.key,
            "value": value,
            "source": "literal",
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def _project_secret_value(parsed: argparse.Namespace) -> str:
    if parsed.value is not None:
        value = str(parsed.value).strip()
        if not value:
            raise machine_secrets.MachineSecretError("secret is empty")
        return value
    if parsed.value_file:
        return machine_secrets.read_secret_file(parsed.value_file, "secret")
    return machine_secrets.read_stdin_secret("secret")


def _store_machine_local_secret(parsed: argparse.Namespace, value: str) -> int:
    try:
        project_slug = _resolve_project_slug(parsed.project, parsed.session_id)
        local_secrets = importlib.import_module(
            "yoke_core.domain.capability_machine_secrets"
        )
        path = local_secrets.store_machine_capability_secret(
            project_slug,
            parsed.cap_type,
            parsed.key,
            value,
        )
    except Exception as exc:
        print(f"error: machine-local capability secret write failed: {exc}",
              file=sys.stderr)
        return 1

    return dispatch_and_emit(
        function_id="projects.capability_secret.set",
        target=TargetRef(kind="global"),
        payload={
            "project": project_slug,
            "cap_type": parsed.cap_type,
            "key": parsed.key,
            "source": "machine_file",
            "path": str(path),
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_machine_local_human_writer,
    )


def _resolve_project_slug(project: str, session_id: str | None) -> str:
    ensure_handlers_loaded()
    response = call_dispatcher(
        function_id="projects.get",
        target=TargetRef(kind="global"),
        payload={"project": project, "field": "slug"},
        actor=build_actor(session_id=session_id),
    )
    if response.success:
        value = (response.result or {}).get("value")
        if isinstance(value, str) and value.strip():
            return value.strip()
    message = (
        response.error.message
        if response.error is not None
        else f"project {project!r} did not resolve to a slug"
    )
    raise machine_secrets.MachineSecretError(message)


def _machine_local_human_writer(response, stdout, stderr) -> None:
    del stderr
    result = response.result or {}
    stdout.write(
        "Stored machine-local secret "
        f"{result.get('cap_type')}.{result.get('key')} for project "
        f"{result.get('project')} at {result.get('path')}\n"
    )


__all__ = [
    "PROJECTS_CAPABILITY_SECRET_SET_USAGE",
    "projects_capability_secret_set",
]
