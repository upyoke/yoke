"""Canonical reader for Yoke's machine-local settings.

Default reads come from ``~/.yoke/config.json`` under the ``settings``
object. Explicit ``config_path`` arguments still parse key=value fixtures for
tests and legacy operator-debug paths.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterable

from yoke_core.domain import machine_config

__all__ = ["get_int", "get_seconds", "get_str", "main", "read_all"]


def _canonical_config_path() -> Path:
    return machine_config.config_path()


def _strip_value(raw_value: str) -> str:
    value = raw_value.split("#", 1)[0].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def read_all(config_path: Path | str | None = None) -> dict[str, str]:
    if config_path is None:
        return machine_config.read_settings()
    path = Path(config_path)
    if path.suffix.lower() == ".json":
        return machine_config.read_settings(path)
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw_value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        values[key] = _strip_value(raw_value)
    return values


def get_str(key: str, default: str, *, config_path: Path | str | None = None) -> str:
    return read_all(config_path).get(key, default)


def get_int(key: str, default: int, *, config_path: Path | str | None = None) -> int:
    raw = read_all(config_path).get(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def get_seconds(key: str, default: int, *, config_path: Path | str | None = None) -> int:
    value = get_int(key, default, config_path=config_path)
    if value <= 0:
        return default
    return value


def main(argv: Iterable[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    if not args or args[0] != "get":
        sys.stderr.write(
            "Usage: python3 -m yoke_core.domain.runtime_settings get <key> [default]\n"
        )
        return 0
    key = args[1] if len(args) > 1 else ""
    default = args[2] if len(args) > 2 else ""
    if not key:
        sys.stdout.write(f"{default}\n")
        return 0
    sys.stdout.write(f"{get_str(key, default)}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
