"""Read CLI project references once before dispatch, without explicit-env fiction."""

from contextlib import contextmanager
import os
import re

from yoke_cli.config import machine_config
from yoke_contracts.machine_config.schema_connections import MachineConfigContractError
from yoke_contracts.machine_config.selection import (
    PROJECT_CONNECTION,
    SELECTION_REASON,
    connection_groups,
    connection_selection,
    checkout_connection,
)


def project_references(args: list[str]) -> tuple[set[str], set[str]]:
    projects, prefixes = set(), set()
    tokens = args[: args.index("--")] if "--" in args else args
    for index, token in enumerate(tokens):
        if token == "--project" and index + 1 < len(tokens):
            projects.add(tokens[index + 1])
        elif token.startswith("--project="):
            projects.add(token.split("=", 1)[1])
        elif re.fullmatch(r"[A-Z][A-Z0-9]*-[1-9][0-9]*", token):
            prefixes.add(token.rsplit("-", 1)[0])
    return projects, prefixes


def referenced_connection(payload: dict, args: list[str]) -> str:
    projects, prefixes = project_references(args)
    if not projects and not prefixes:
        return ""
    matches = set()
    for env, entries in connection_groups(payload).items():
        ids = {str(entry["project_id"]) for entry in entries}
        if not ids:
            continue
        if projects & ids:
            matches.add(env)
        if prefixes or any(not project.isdecimal() for project in projects):
            for row in _project_rows(env):
                if str(row.get("id")) not in ids:
                    continue
                if (
                    row.get("slug") in projects
                    or row.get("public_item_prefix") in prefixes
                ):
                    matches.add(env)
    # A reference duplicated across universes supplies no unique routing fact.
    return matches.pop() if len(matches) == 1 else ""


def _project_rows(env: str) -> list[dict]:
    from yoke_cli.commands.local_dispatch_preload import ensure_handlers_loaded
    from yoke_cli.transport.dispatcher import call_dispatcher
    from yoke_contracts.api.function_call import ActorContext, TargetRef

    previous = os.environ.get("YOKE_ENV")
    try:
        os.environ["YOKE_ENV"] = env
        ensure_handlers_loaded()
        response = call_dispatcher(
            function_id="projects.list",
            target=TargetRef(kind="global"),
            payload={"fields": ["id", "slug", "public_item_prefix"]},
            actor=ActorContext(actor_id=None, session_id=""),
            timeout_s=10,
            max_attempts=1,
        )
    finally:
        if previous is None:
            os.environ.pop("YOKE_ENV", None)
        else:
            os.environ["YOKE_ENV"] = previous
    if not response.success:
        code = response.error.code if response.error else "unknown"
        raise MachineConfigContractError(
            f"project_reference_connection_unavailable: cannot inspect {env!r} "
            f"({code}); pass --env ENV to select the intended connection"
        )
    return (response.result or {}).get("rows", [])


@contextmanager
def command_connection(args: list[str], explicit_env: str | None):
    """Scope inferred routing and its diagnostic reason to this invocation."""
    reason_token = SELECTION_REASON.set("explicit_flag" if explicit_env else "")
    project_token = PROJECT_CONNECTION.set("")
    try:
        if not explicit_env and not os.environ.get("YOKE_ENV", "").strip():
            if not any(token in ("--help", "-h", "help") for token in args):
                payload = machine_config.load_config()
                if not checkout_connection(payload):
                    PROJECT_CONNECTION.set(referenced_connection(payload, args))
        yield
    finally:
        PROJECT_CONNECTION.reset(project_token)
        SELECTION_REASON.reset(reason_token)


def write_connection_selection(stdout) -> None:
    env, reason = connection_selection(machine_config.load_config())
    print(f"connection: {env}\nconnection_source: {reason}", file=stdout)


def enrich_checkout_context(response, actor):
    """Attach client-owned connection evidence to both JSON and human replies."""
    if response.success:
        env, reason = connection_selection(machine_config.load_config())
        response = response.model_copy(
            update={
                "result": {
                    **(response.result or {}),
                    "connection": env,
                    "connection_source": reason,
                }
            }
        )
    return response
