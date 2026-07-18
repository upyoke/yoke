"""``yoke`` — the unified agent-facing operations CLI.

Single entrypoint for every Yoke-owned function-call. Resolves the
subcommand against :mod:`yoke_cli.commands.registry`, delegates flag
parsing + payload construction to the matching adapter in
:mod:`yoke_cli.commands.flag_adapters`, and routes the envelope by the
active connection: https connections POST the ``FunctionCallRequest``
to ``{api_url}/v1/functions/call``; local-postgres connections dispatch
in-process through
:func:`yoke_core.domain.yoke_function_dispatch.dispatch` — the product
path for a non-prod local universe. Same envelope, same payload, same
auth, same handler across both branches.
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional, Sequence

from yoke_cli.commands.registry import (
    SUBCOMMAND_REGISTRY,
    resolve,
)
from yoke_cli.commands.flag_adapters import ADAPTER_USAGE
from yoke_cli.commands.group_help import emit_group_help_if_available
from yoke_cli.commands.help_labels import labeled_cli_form
from yoke_cli.commands.manifest_drift import (
    manifest_unknown_hint,
    render_manifest_drift,
)
from yoke_cli.commands.tool_shaped import (
    TOOL_SHAPED_USAGE,
    resolve_tool_shaped,
)
from yoke_cli.config import install_binding, machine_config
from yoke_contracts.field_note_text import FOOTER as _FIELD_NOTE_FOOTER
from yoke_contracts.machine_config import schema as machine_schema
from yoke_contracts.machine_config.schema import ENV_OVERRIDE


_BARE_ONBOARD_COMMAND = "yoke onboard"
_NONINTERACTIVE_ONBOARD_COMMAND = (
    "yoke onboard --non-interactive --local --yes   (machine-local universe)\n"
    "  yoke onboard --non-interactive --env <env> --api-url <url> "
    "--token-file <path> --yes"
)


_TOP_LEVEL_HELP_HEADER = """\
yoke — Yoke operations CLI.

Usage:
  yoke [--env NAME] <namespace> <entity> <verb> [args...]
  yoke <namespace> <entity> <verb> [args...]
  yoke --help
  yoke --version

Every subcommand mirrors a Yoke function id. Dots become spaces;
underscores inside a segment become hyphens; synthetic terminal
``.run`` / ``.execute`` segments drop. The translation is reversible
by mechanical rule — no lookup table required.

Available subcommands (grouped by family):
"""


def _render_help() -> str:
    lines: List[str] = [_TOP_LEVEL_HELP_HEADER]
    rows: List[tuple[str, str, str]] = []
    for cli_tokens, (function_id, _adapter) in sorted(SUBCOMMAND_REGISTRY.items()):
        cli_form = "yoke " + " ".join(cli_tokens)
        usage = ADAPTER_USAGE.get(function_id, "")
        rows.append((cli_form, function_id, usage))

    family_groups: dict[str, list[tuple[str, str, str]]] = {}
    for cli_form, function_id, usage in rows:
        family = function_id.split(".", 1)[0]
        family_groups.setdefault(family, []).append((cli_form, function_id, usage))

    tool_shaped_groups: dict[str, list[tuple[str, str]]] = {}
    for cli_form, usage in TOOL_SHAPED_USAGE.items():
        tokens = cli_form.split()
        family = (
            tokens[1]
            if len(tokens) > 1 and tokens[0] == "yoke"
            else "tool-shaped"
        )
        tool_shaped_groups.setdefault(family, []).append((cli_form, usage))

    for family in sorted(set(family_groups.keys()) | set(tool_shaped_groups.keys())):
        lines.append(f"\n  [{family}]")
        for cli_form, function_id, usage in family_groups.get(family, []):
            lines.append(f"    {labeled_cli_form(cli_form)}")
            lines.append(f"      -> {function_id}")
            if usage:
                lines.append(f"      {usage}")
        for cli_form, usage in sorted(tool_shaped_groups.get(family, [])):
            lines.append(f"    {labeled_cli_form(cli_form)}")
            lines.append("      -> client-local helper (no function id)")
            if usage:
                lines.append(f"      {usage}")
    lines.append("")
    lines.append(
        "Subcommand-specific help: every subcommand also accepts standard "
        "argparse flags. Invoke with a bad/missing flag to see usage."
    )
    lines.append(
        "Session id resolves from $YOKE_SESSION_ID (or --session-id "
        "override); actor id is filled server-side from harness_sessions."
    )
    # The field-note footer lands on every `yoke --help`
    # invocation so the operator-facing channel for the Ouroboros learning
    # loop is one screen away from every CLI agent surface. Per-subcommand
    # adapters carry the same footer via argparse's `epilog`; see
    # `yoke_cli.commands._helpers.parse_or_usage_error` for the wiring.
    lines.append("")
    lines.append(_FIELD_NOTE_FOOTER)
    return "\n".join(lines)


def _emit_help() -> int:
    print(_render_help())
    drift = render_manifest_drift()
    if drift:
        print(drift)
    return 0


def _emit_version() -> int:
    print(install_binding.distribution_version(source_value="source") or "unknown")
    return 0


def _emit_bare_onboard_route(problem: str, *, interactive: bool) -> int:
    print(f"yoke: machine config is not ready: {problem}", file=sys.stderr)
    if interactive:
        print(f"Start setup with `{_BARE_ONBOARD_COMMAND}`.", file=sys.stderr)
    else:
        print(
            "Run onboarding explicitly. For automation:",
            file=sys.stderr,
        )
        print(f"  {_NONINTERACTIVE_ONBOARD_COMMAND}", file=sys.stderr)
    print("Help is still available with `yoke --help`.", file=sys.stderr)
    return 1


def _emit_unknown(argv: Sequence[str]) -> int:
    head = " ".join(list(argv)[:3]) if argv else "<no subcommand>"
    hint = manifest_unknown_hint(list(argv)) or (
        "Run `yoke --help` for the canonical list of subcommands."
    )
    print(f"yoke: unknown subcommand: {head!r}\n{hint}", file=sys.stderr)
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
        issue for issue in machine_schema.validate_payload(
            payload, explicit_env=explicit_env,
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


def main(argv: Optional[List[str]] = None) -> int:
    """Run the ``yoke`` CLI for one invocation. Returns the exit code."""
    if argv is None:
        argv = list(sys.argv[1:])
    else:
        argv = list(argv)

    argv, global_env, env_ok = _extract_global_env(argv)
    if not env_ok:
        print("yoke: --env requires a non-empty value", file=sys.stderr)
        return 2

    if not argv:
        ready, problem = _machine_config_ready(global_env)
        if not ready:
            return _emit_bare_onboard_route(
                problem, interactive=_stdin_is_interactive(),
            )
        return _emit_help()

    if argv[0] in ("-h", "--help", "help"):
        return _emit_help()

    if argv[0] in ("-V", "--version", "version"):
        return _emit_version()

    try:
        _cli_tokens, _function_id, adapter, remaining = resolve(argv)
    except KeyError:
        # Tool-shaped commands (git hook bodies, browser-QA orchestration,
        # the client-local installer/onboarding flows) carry no function
        # id; they route here only after registry resolution misses. A
        # concrete tool-shaped match wins over group-prefix help, mirroring
        # how a registry hit wins: only fall back to group help when nothing
        # runnable matches. Without this, a bare tool-shaped command that is
        # also a registered group prefix (`yoke onboard` wizard, with
        # `onboard checklist` registered) would be shadowed by its own group
        # listing instead of launching.
        tool_shaped = resolve_tool_shaped(argv)
        if tool_shaped is not None:
            adapter, remaining = tool_shaped
        else:
            group_help = emit_group_help_if_available(argv)
            if group_help is not None:
                return group_help
            return _emit_unknown(argv)

    old_env = os.environ.get(ENV_OVERRIDE)
    try:
        if global_env:
            os.environ[ENV_OVERRIDE] = global_env
        try:
            return adapter(remaining)
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


if __name__ == "__main__":
    sys.exit(main())
