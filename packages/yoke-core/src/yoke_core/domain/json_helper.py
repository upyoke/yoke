"""JSON helper commands for shell compatibility surfaces."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, Optional, Sequence, TextIO


def dumps_compact(value: object) -> str:
    return json.dumps(value, separators=(",", ":"))


def dumps_pretty(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def loads_text(value: str) -> object:
    return json.loads(value)


def load_path(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_path(path: Path, data: object) -> None:
    path.write_text(dumps_pretty(data), encoding="utf-8")


def _load_json(path: Path) -> object:
    with path.open() as handle:
        return json.load(handle)


def _dump_json(path: Path, data: object) -> None:
    with path.open("w") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")


def _require_file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Error: file not found: {path}")


def cmd_get(file_path: Path, key: str, *, out: TextIO) -> int:
    _require_file(file_path)
    data = _load_json(file_path)
    if not isinstance(data, dict):
        value = ""
    else:
        value = data.get(key, "")
    if isinstance(value, str):
        out.write(f"{value}\n")
    elif isinstance(value, (int, float, bool)):
        out.write(f"{value}\n")
    elif value is None:
        out.write("\n")
    else:
        out.write(json.dumps(value) + "\n")
    return 0


def cmd_set(file_path: Path, key: str, value: str) -> int:
    _require_file(file_path)
    data = _load_json(file_path)
    if not isinstance(data, dict):
        raise ValueError("Error: JSON root must be an object")
    data[key] = value
    _dump_json(file_path, data)
    return 0


def cmd_set_int(file_path: Path, key: str, value: str) -> int:
    _require_file(file_path)
    data = _load_json(file_path)
    if not isinstance(data, dict):
        raise ValueError("Error: JSON root must be an object")
    data[key] = int(value)
    _dump_json(file_path, data)
    return 0


def cmd_increment(file_path: Path, key: str) -> int:
    _require_file(file_path)
    data = _load_json(file_path)
    if not isinstance(data, dict):
        raise ValueError("Error: JSON root must be an object")
    data[key] = int(data.get(key, 0)) + 1
    _dump_json(file_path, data)
    return 0


def cmd_append(file_path: Path, key: str, json_obj: str) -> int:
    _require_file(file_path)
    data = _load_json(file_path)
    if not isinstance(data, dict):
        raise ValueError("Error: JSON root must be an object")
    try:
        entry = json.loads(json_obj)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Error: invalid JSON for append value: {exc}") from exc
    data.setdefault(key, [])
    if not isinstance(data[key], list):
        raise ValueError(f"Error: field '{key}' is not an array")
    data[key].append(entry)
    _dump_json(file_path, data)
    return 0


def cmd_create(file_path: Path, json_str: str) -> int:
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Error: invalid JSON for create: {exc}") from exc
    _dump_json(file_path, data)
    return 0


def cmd_csv_to_array(csv_text: str, *, out: TextIO) -> int:
    items = [part.strip() for part in csv_text.split(",") if part.strip()]
    out.write(json.dumps(items) + "\n")
    return 0


def run_command(argv: Sequence[str], *, out: TextIO, err: TextIO) -> int:
    if not argv:
        err.write("Usage: json-helper.sh <command> [args]\n")
        return 1

    cmd = argv[0]
    args = list(argv[1:])
    try:
        if cmd == "get":
            if len(args) < 2:
                err.write("Usage: json-helper.sh get <file> <key>\n")
                return 1
            return cmd_get(Path(args[0]), args[1], out=out)
        if cmd == "set":
            if len(args) < 3:
                err.write("Usage: json-helper.sh set <file> <key> <value>\n")
                return 1
            return cmd_set(Path(args[0]), args[1], args[2])
        if cmd == "set-int":
            if len(args) < 3:
                err.write("Usage: json-helper.sh set-int <file> <key> <value>\n")
                return 1
            return cmd_set_int(Path(args[0]), args[1], args[2])
        if cmd == "increment":
            if len(args) < 2:
                err.write("Usage: json-helper.sh increment <file> <key>\n")
                return 1
            return cmd_increment(Path(args[0]), args[1])
        if cmd == "append":
            if len(args) < 3:
                err.write("Usage: json-helper.sh append <file> <key> <json-object-string>\n")
                return 1
            return cmd_append(Path(args[0]), args[1], args[2])
        if cmd == "create":
            if len(args) < 2:
                err.write("Usage: json-helper.sh create <file> <json-string>\n")
                return 1
            return cmd_create(Path(args[0]), args[1])
        if cmd == "csv-to-array":
            if len(args) < 1:
                err.write("Usage: json-helper.sh csv-to-array <csv-string>\n")
                return 1
            return cmd_csv_to_array(args[0], out=out)
    except (FileNotFoundError, ValueError) as exc:
        err.write(f"{exc}\n")
        return 1

    err.write(f"Unknown command: {cmd}\n")
    err.write("Commands: get, set, set-int, increment, append, create, csv-to-array\n")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="json-helper",
        description="JSON helper compatibility commands",
        add_help=False,
    )
    parser.add_argument("command", nargs="?")
    parser.add_argument("args", nargs="*")
    return parser


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_parser()
    parsed = parser.parse_args(list(argv) if argv is not None else None)
    command = parsed.command
    if command is None:
        print("Usage: json-helper.sh <command> [args]", file=sys.stderr)
        return 1
    return run_command([command, *parsed.args], out=sys.stdout, err=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
