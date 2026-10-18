"""Route one ``yoke`` invocation through the command registry.

Resolves the subcommand against :mod:`yoke_cli.commands.registry`, delegates
flag parsing + payload construction to the matching adapter in
:mod:`yoke_cli.commands.flag_adapters`, and routes the envelope by the
active connection: https connections POST the ``FunctionCallRequest``
to ``{api_url}/v1/functions/call``; local-postgres connections dispatch
in-process through
:func:`yoke_core.domain.yoke_function_dispatch.dispatch` — the product
path for a non-prod local universe. Same envelope, same payload, same
auth, same handler across both branches.

Importing this module loads the whole command catalog, so the ``yoke``
entrypoint (:mod:`yoke_cli.main`) imports it only after the hook fast path
has declined the invocation.
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional, Sequence

from yoke_cli.commands.registry import (
    resolve,
)
from yoke_cli.commands.command_tree import render_root_help
from yoke_cli.commands.group_help import (
    emit_group_help_if_available,
    emit_nearest_group_help,
    nearest_subcommand_hint,
)
from yoke_cli.commands.manifest_drift import (
    manifest_unknown_hint,
    render_manifest_drift,
)
from yoke_cli.commands.tool_shaped import (
    resolve_tool_shaped,
)
from yoke_cli.conceptual_cli_names import conceptual_cli_hint
from yoke_cli.config import install_binding, machine_config
from yoke_cli import sandbox_denial
from yoke_cli.transport.output_limit import read_output_scope
from yoke_cli.session_id_propagation import propagated_session_identity
from yoke_cli.invocation_locality import control_plane_locality
from yoke_contracts.machine_config import schema as machine_schema
from yoke_contracts.machine_config.schema import ENV_OVERRIDE
from yoke_contracts.field_note_text import FOOTER as FIELD_NOTE_FOOTER


_BARE_SETUP_COMMAND = "yoke setup"
_AGENT_SETUP_COMMAND = "yoke setup --agent"
_NONINTERACTIVE_SETUP_COMMAND = (
    "yoke setup --non-interactive --local --yes   (machine-local universe)\n"
    "  yoke setup --non-interactive --env <env> --api-url <url> "
    "--token-file <path> --yes"
)


def _render_help() -> str:
    return render_root_help() + "\n\n" + FIELD_NOTE_FOOTER


def _emit_help(*, explicit_env: Optional[str] = None) -> int:
    print(_render_help())
    drift = render_manifest_drift(explicit_env=explicit_env)
    if drift:
        print(drift)
    return 0


def _emit_version() -> int:
    print(install_binding.distribution_version(source_value="source") or "unknown")
    return 0


def _emit_bare_setup_route(problem: str, *, interactive: bool) -> int:
    print(f"yoke: machine config is not ready: {problem}", file=sys.stderr)
    if interactive:
        print(f"Start setup with `{_BARE_SETUP_COMMAND}`.", file=sys.stderr)
    else:
        print(
            f"From a coding agent, run `{_AGENT_SETUP_COMMAND}` and answer "
            "its questions one at a time. For automation:",
            file=sys.stderr,
        )
        print(f"  {_NONINTERACTIVE_SETUP_COMMAND}", file=sys.stderr)
    print("Help is still available with `yoke --help`.", file=sys.stderr)
    return 1


def _emit_unknown(
    argv: Sequence[str],
    *,
    explicit_env: Optional[str] = None,
) -> int:
    head = " ".join(list(argv)[:3]) if argv else "<no subcommand>"
    conceptual = conceptual_cli_hint(argv)
    hint = (
        conceptual
        or manifest_unknown_hint(
            list(argv),
            explicit_env=explicit_env,
        )
        or nearest_subcommand_hint(argv)
        or ("Run `yoke --help` for the canonical list of subcommands.")
    )
    print(f"yoke: unknown subcommand: {head!r}\n{hint}", file=sys.stderr)
    if conceptual is None:
        emit_nearest_group_help(argv, stream=sys.stderr)
    return 2


def _emit_interrupted() -> int:
    print("yoke: interrupted by Ctrl-C.", file=sys.stderr)
    return 130


def _machine_config_ready(explicit_env: Optional[str]) -> tuple[bool, str]:
    selected_path = machine_config.config_path()
    if not selected_path.is_file():
        return False, f"machine config not found at {selected_path}"
    try:
        payload = machine_config.load_config(selected_path)
    except machine_config.MachineConfigError as exc:
        return False, str(exc)
    errors = [
        issue
        for issue in machine_schema.validate_payload(
            payload,
            explicit_env=explicit_env,
        )
        if issue.severity == "error"
    ]
    if errors:
        return False, errors[0].message
    try:
        machine_schema.active_connection(
            machine_schema.normalize_payload(payload),
            explicit_env=explicit_env,
        )
    except machine_schema.MachineConfigContractError as exc:
        return False, str(exc)
    return True, ""


def _stdin_is_interactive() -> bool:
    isatty = getattr(sys.stdin, "isatty", None)
    return bool(callable(isatty) and isatty())


def _extract_global_env(argv: List[str]) -> tuple[List[str], Optional[str], bool]:
    out: List[str] = []
    selected: Optional[str] = None
    i = 0
    while i < len(argv):
        token = argv[i]
        if token == "--":
            out.extend(argv[i:])
            break
        if token == "--env":
            if i + 1 >= len(argv) or not argv[i + 1].strip():
                return argv, None, False
            selected = argv[i + 1].strip()
            i += 2
            continue
        if token.startswith("--env="):
            selected = token.split("=", 1)[1].strip()
            if not selected:
                return argv, None, False
            i += 1
            continue
        out.append(token)
        i += 1
    return out, selected, True


def route_command(argv: List[str]) -> int:
    """Run one registry-routed ``yoke`` invocation. Returns the exit code."""
    argv, global_env, env_ok = _extract_global_env(argv)
    if not env_ok:
        print("yoke: --env requires a non-empty value", file=sys.stderr)
        return 2

    if not argv:
        ready, problem = _machine_config_ready(global_env)
        if not ready:
            return _emit_bare_setup_route(
                problem,
                interactive=_stdin_is_interactive(),
            )
        return _emit_help(explicit_env=global_env)

    if argv[0] in ("-h", "--help", "help"):
        return _emit_help(explicit_env=global_env)

    if argv[0] in ("-V", "--version", "version"):
        return _emit_version()

    if argv[-1] in ("-h", "--help", "help"):
        from yoke_cli.commands.command_tree import command_routes
        from yoke_cli.commands.group_help import can_route_group

        prefix = tuple(argv[:-1])
        if can_route_group(prefix):
            group_result = emit_group_help_if_available(argv)
            if prefix not in command_routes():
                return group_result if group_result is not None else 0
            argv[-1] = "--help"

    _function_id = None
    try:
        _cli_tokens, _function_id, adapter, remaining = resolve(argv)
    except KeyError:
        # Tool-shaped commands (git hook bodies, QA case/substrate tools,
        # the client-local installer/onboarding flows) carry no function
        # id; they route here only after registry resolution misses.
        # Concrete client-local commands win over prefix-group help, just as
        # registered commands do. Bare onboard now falls through to the
        # project-readiness group; only setup launches the machine wizard.
        tool_shaped = resolve_tool_shaped(argv)
        if tool_shaped is not None:
            adapter, remaining = tool_shaped
        else:
            group_help = emit_group_help_if_available(argv)
            if group_help is not None:
                return group_help
            return _emit_unknown(argv, explicit_env=global_env)

    old_env = os.environ.get(ENV_OVERRIDE)
    try:
        if global_env:
            os.environ[ENV_OVERRIDE] = global_env
        # Marked here, around the adapter rather than around the relay,
        # because the code that must not open a connection is the engine work
        # the adapter runs locally — worktree preflight, merge, resync,
        # GitHub sync — not the relay call itself.
        with (
            control_plane_locality(global_env),
            propagated_session_identity(argv),
            read_output_scope(remaining, _function_id),
        ):
            try:
                return sandbox_denial.run(adapter, remaining, argv)
            except SystemExit as exc:
                return exc.code if isinstance(exc.code, int) else 1
            except KeyboardInterrupt:
                return _emit_interrupted()
    finally:
        if global_env:
            if old_env is None:
                os.environ.pop(ENV_OVERRIDE, None)
            else:
                os.environ[ENV_OVERRIDE] = old_env
