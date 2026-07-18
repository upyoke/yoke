"""YAML frontmatter helper commands for shell compatibility surfaces."""

from __future__ import annotations

import os
import re
import shutil
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional, Sequence, TextIO

import yaml


def load_document(path: Path) -> Any:
    """Load one YAML document through the project-owned parser boundary."""
    _require_file(path)
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def parse_document(text: str):
    """Parse one YAML document through the project-owned safe loader."""

    import yaml

    return yaml.safe_load(text)


def read_top_level_scalars(path: Path, keys: Iterable[str]) -> dict[str, str]:
    """Read an exact set of unindented scalar fields from a YAML file.

    This deliberately narrow reader is for machine-generated authority
    metadata such as Pulumi's ``secretsprovider`` and ``encryptedkey`` fields.
    It does not pretend to be a general YAML parser, but it keeps YAML reads
    behind the project-owned helper and refuses duplicate fields.
    """
    _require_file(path)
    selected = {str(key).strip() for key in keys if str(key).strip()}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line[:1].isspace() or line.lstrip().startswith("#"):
            continue
        key, separator, raw_value = line.partition(":")
        key = key.strip()
        if not separator or key not in selected:
            continue
        if key in values:
            raise ValueError(f"duplicate top-level YAML field: {key}")
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        values[key] = value
    return values


def _resolve_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    invoke_dir = os.environ.get("YOKE_YAML_HELPER_CWD")
    if invoke_dir:
        return Path(invoke_dir) / path
    return path


def _require_file(path: Path) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"Error: file not found: {path}")


def _read_lines(path: Path) -> list[str]:
    return path.read_text().splitlines(keepends=True)


def _split_frontmatter(lines: list[str]) -> tuple[dict[str, str], int | None]:
    if not lines or lines[0].strip() != "---":
        return {}, None
    fields: dict[str, str] = {}
    for index, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            return fields, index
        if ":" in line:
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields, len(lines) - 1


def _repo_config(path: Path) -> dict[str, str]:
    for parent in [path.parent, *path.parents]:
        config_file = parent / "runtime" / "config"
        if config_file.is_file():
            config: dict[str, str] = {}
            for line in config_file.read_text().splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                config[key.strip()] = value.split("#", 1)[0].strip()
            return config
    return {}


@contextmanager
def _lock(path: Path, *, enabled: bool) -> Iterator[None]:
    if not enabled:
        yield
        return

    lockdir = Path(f"{path}.lock")
    config = _repo_config(path)
    retries = int(config.get("lock_retries", "50") or "50")
    sleep_ms = int(config.get("lock_sleep_ms", "100") or "100")
    stale_seconds = int(config.get("lock_stale_seconds", "60") or "60")
    attempt = 0
    while True:
        try:
            os.mkdir(lockdir)
            break
        except FileExistsError:
            attempt += 1
            if lockdir.exists():
                age = time.time() - lockdir.stat().st_mtime
                if age > stale_seconds:
                    shutil.rmtree(lockdir, ignore_errors=True)
                    attempt = 0
                    continue
            if attempt > retries:
                raise RuntimeError(f"Error: Could not acquire lock after {retries} retries: {lockdir}")
            time.sleep(sleep_ms / 1000.0)
    try:
        yield
    finally:
        try:
            os.rmdir(lockdir)
        except OSError:
            pass


def cmd_get(file_path: Path, field: str, *, out: TextIO) -> int:
    _require_file(file_path)
    fields, _ = _split_frontmatter(_read_lines(file_path))
    out.write(fields.get(field, "") + "\n")
    return 0


def cmd_set(file_path: Path, field: str, value: str, *, no_lock: bool) -> int:
    _require_file(file_path)
    lines = _read_lines(file_path)
    if not lines or lines[0].strip() != "---":
        raise ValueError("Error: file has no YAML frontmatter")

    timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    temp = Path(f"{file_path}.tmp.{os.getpid()}")
    with _lock(file_path, enabled=not no_lock):
        result: list[str] = []
        field_updated = False
        in_fm = False
        fm_count = 0
        for line in lines:
            stripped = line.strip()
            if stripped == "---":
                fm_count += 1
                if fm_count == 1:
                    in_fm = True
                elif fm_count == 2:
                    if not field_updated:
                        result.append(f"{field}: {value}\n")
                    in_fm = False
                result.append(line)
                continue
            if in_fm and ":" in line:
                key = line.split(":", 1)[0].strip()
                if key == field:
                    result.append(f"{field}: {value}\n")
                    field_updated = True
                    continue
                if key == "updated" and field != "updated":
                    result.append(f"updated: {timestamp}\n")
                    continue
            result.append(line)
        temp.write_text("".join(result))
        os.replace(temp, file_path)
    return 0


def cmd_strip(file_path: Path, *, out: TextIO) -> int:
    _require_file(file_path)
    lines = _read_lines(file_path)
    if not lines or lines[0].strip() != "---":
        out.write("".join(lines))
        return 0
    _, end = _split_frontmatter(lines)
    body = lines[(end + 1 if end is not None else 1) :]
    out.write("".join(body))
    return 0


def cmd_strip_to_file(file_path: Path, out_file: Path) -> int:
    text_out = []

    class _Writer:
        def write(self, value: str) -> int:
            text_out.append(value)
            return len(value)

    cmd_strip(file_path, out=_Writer())
    out_file.write_text("".join(text_out))
    return 0


def cmd_first_heading(file_path: Path, *, out: TextIO) -> int:
    _require_file(file_path)
    lines = _read_lines(file_path)
    start = 0
    if lines and lines[0].strip() == "---":
        _, end = _split_frontmatter(lines)
        start = end + 1 if end is not None else 1
    for line in lines[start:]:
        match = re.match(r"^#+\s+(.*)", line)
        if match:
            out.write(match.group(1) + "\n")
            break
    return 0


def cmd_create(file_path: Path, pairs: Sequence[str]) -> int:
    lines = ["---\n"]
    for pair in pairs:
        if "=" in pair:
            key, value = pair.split("=", 1)
            lines.append(f"{key}: {value}\n")
    lines.append("---\n")
    file_path.write_text("".join(lines))
    return 0


def run_command(argv: Sequence[str], *, out: TextIO, err: TextIO) -> int:
    if not argv:
        err.write("Usage: yaml-helper.sh <command> [args]\n")
        return 1

    cmd = argv[0]
    args = list(argv[1:])
    try:
        if cmd == "get":
            if len(args) < 2:
                err.write("Usage: yaml-helper.sh get <file> <field>\n")
                return 1
            return cmd_get(_resolve_path(args[0]), args[1], out=out)
        if cmd == "set":
            no_lock = False
            if args and args[0] == "--no-lock":
                no_lock = True
                args = args[1:]
            if len(args) < 3:
                err.write("Usage: yaml-helper.sh set [--no-lock] <file> <field> <value>\n")
                return 1
            return cmd_set(_resolve_path(args[0]), args[1], args[2], no_lock=no_lock)
        if cmd == "strip":
            if len(args) < 1:
                err.write("Usage: yaml-helper.sh strip <file>\n")
                return 1
            return cmd_strip(_resolve_path(args[0]), out=out)
        if cmd == "strip-to-file":
            if len(args) < 2:
                err.write("Usage: yaml-helper.sh strip-to-file <file> <outfile>\n")
                return 1
            return cmd_strip_to_file(_resolve_path(args[0]), _resolve_path(args[1]))
        if cmd == "first-heading":
            if len(args) < 1:
                err.write("Usage: yaml-helper.sh first-heading <file>\n")
                return 1
            return cmd_first_heading(_resolve_path(args[0]), out=out)
        if cmd == "create":
            if len(args) < 1:
                err.write("Usage: yaml-helper.sh create <file> <field1=value1> [field2=value2] ...\n")
                return 1
            return cmd_create(_resolve_path(args[0]), args[1:])
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        err.write(f"{exc}\n")
        return 1

    err.write(f"Unknown command: {cmd}\n")
    err.write("Commands: get, set, strip, strip-to-file, first-heading, create\n")
    return 1


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    if not args:
        print("Usage: yaml-helper.sh <command> [args]", file=sys.stderr)
        return 1
    return run_command(args, out=sys.stdout, err=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
