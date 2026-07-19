"""Allowlisted Pulumi child-command construction for exact-stack execution."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
import re

from yoke_core.tools.pulumi_exec_types import PulumiExecError


_ALLOWED_COMMANDS = frozenset({"init", "preview", "refresh", "import", "up", "stack"})
_OUTPUT_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*")
_IMPORT_FLAGS = frozenset(
    {"--protect=false", "--generate-code=false", "--yes", "--non-interactive"}
)
_PREVIEW_FLAGS = frozenset(
    {
        "--diff",
        "--expect-no-changes",
        "--non-interactive",
        "--refresh",
        "--suppress-outputs",
    }
)
_REFRESH_FLAGS = frozenset(
    {"--non-interactive", "--preview-only", "--skip-preview", "--yes"}
)
_UP_FLAGS = frozenset(
    {"--diff", "--non-interactive", "--refresh", "--suppress-outputs", "--yes"}
)


def validated_command(
    stack: str, command: Sequence[str]
) -> tuple[list[str], Path | None]:
    parts = [str(part) for part in command]
    if not parts or parts[0] not in _ALLOWED_COMMANDS:
        raise PulumiExecError(
            "Pulumi exec allows only init, preview, refresh, import, up, and "
            "single-name stack output reads"
        )
    operation = parts[0]
    if operation == "init":
        raise PulumiExecError("Pulumi init must use the stack bootstrap boundary")
    args = parts[1:]
    _assert_stack_flag(args, stack)
    if operation == "stack":
        return _validated_stack_output(stack, args), None
    json_output: Path | None = None
    if operation == "import":
        _validate_import_args(args)
        args = _absolute_option_path(args, "--file")
    elif operation == "preview":
        args, json_output = _preview_output_args(args)
        _validate_flag_args(args, _PREVIEW_FLAGS, path_options={"--import-file"})
        args = _absolute_option_path(args, "--import-file")
        if json_output is not None:
            args.append("--json")
    elif operation == "up":
        _validate_up_args(args)
    else:
        _validate_flag_args(args, _REFRESH_FLAGS)
    args = _without_stack_flag(args)
    return ["pulumi", operation, *args, "--stack", stack], json_output


def _validated_stack_output(stack: str, args: Sequence[str]) -> list[str]:
    selected = _without_stack_flag(args)
    if len(selected) not in {2, 3} or selected[0] != "output":
        raise PulumiExecError(
            "Pulumi exec stack reads require exactly `stack output NAME [--json]`"
        )
    output_name = selected[1]
    if not _OUTPUT_NAME.fullmatch(output_name):
        raise PulumiExecError("Pulumi stack output name is invalid")
    flags = selected[2:]
    if flags not in ([], ["--json"]):
        raise PulumiExecError(
            "Pulumi stack output allows only one output name and optional --json"
        )
    return ["pulumi", "stack", "output", output_name, *flags, "--stack", stack]


def _assert_stack_flag(args: Sequence[str], stack: str) -> None:
    index = 0
    while index < len(args):
        value = args[index]
        if value == "--stack":
            if index + 1 >= len(args) or args[index + 1] != stack:
                raise PulumiExecError("child --stack must match the requested stack")
            index += 2
            continue
        if value.startswith("--stack=") and value.split("=", 1)[1] != stack:
            raise PulumiExecError("child --stack must match the requested stack")
        index += 1


def _without_stack_flag(args: Sequence[str]) -> list[str]:
    result: list[str] = []
    index = 0
    while index < len(args):
        value = args[index]
        if value == "--stack":
            index += 2
        elif value.startswith("--stack="):
            index += 1
        else:
            result.append(value)
            index += 1
    return result


def _validate_import_args(args: Sequence[str]) -> None:
    normalized: list[str] = []
    index = 0
    file_count = 0
    while index < len(args):
        value = args[index]
        if value == "--stack":
            index += 2
            continue
        if value.startswith("--stack="):
            index += 1
            continue
        if value == "--file":
            if index + 1 >= len(args):
                raise PulumiExecError("pulumi import --file requires a path")
            file_count += 1
            normalized.extend((value, args[index + 1]))
            index += 2
            continue
        if value in _IMPORT_FLAGS:
            normalized.append(value)
            index += 1
            continue
        raise PulumiExecError(f"pulumi import argument is not allowed: {value}")
    if file_count != 1:
        raise PulumiExecError("pulumi import requires exactly one --file")


def _validate_flag_args(
    args: Sequence[str],
    allowed_flags: frozenset[str],
    *,
    path_options: frozenset[str] | set[str] = frozenset(),
) -> None:
    index = 0
    while index < len(args):
        value = args[index]
        if value == "--stack":
            index += 2
            continue
        if value.startswith("--stack="):
            index += 1
            continue
        if value in path_options:
            if index + 1 >= len(args):
                raise PulumiExecError(f"{value} requires a path")
            index += 2
            continue
        if any(value.startswith(f"{option}=") for option in path_options):
            index += 1
            continue
        if value not in allowed_flags:
            raise PulumiExecError(
                f"Pulumi argument is not allowed for this operation: {value}"
            )
        index += 1


def _validate_up_args(args: Sequence[str]) -> None:
    _validate_flag_args(args, _UP_FLAGS)
    selected = set(_without_stack_flag(args))
    missing = [
        required
        for required in ("--yes", "--non-interactive")
        if required not in selected
    ]
    if missing:
        raise PulumiExecError("pulumi up requires --yes and --non-interactive")


def _preview_output_args(args: Sequence[str]) -> tuple[list[str], Path | None]:
    result: list[str] = []
    output: Path | None = None
    index = 0
    while index < len(args):
        if args[index] == "--json-output":
            if output is not None or index + 1 >= len(args):
                raise PulumiExecError("--json-output requires one unique path")
            output = Path(args[index + 1]).expanduser().resolve()
            index += 2
        else:
            result.append(args[index])
            index += 1
    return result, output


def _absolute_option_path(args: Sequence[str], option: str) -> list[str]:
    result = list(args)
    for index, value in enumerate(result):
        if value == option:
            if index + 1 >= len(result):
                raise PulumiExecError(f"{option} requires a path")
            result[index + 1] = str(Path(result[index + 1]).expanduser().resolve())
        elif value.startswith(f"{option}="):
            result[index] = (
                f"{option}={Path(value.split('=', 1)[1]).expanduser().resolve()}"
            )
    return result


__all__ = ["validated_command"]
