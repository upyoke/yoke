"""Canonical reader for Yoke's machine-local settings.

Default reads come from ``~/.yoke/config.json`` under the ``settings``
object. Explicit ``config_path`` arguments still parse key=value fixtures for
tests and legacy operator-debug paths.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable

from yoke_core.domain import machine_config
from yoke_contracts.machine_config.settings_keys import MACHINE_SETTING_KEYS

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
        value = _strip_value(raw_value)
        spec = MACHINE_SETTING_KEYS.get(key)
        # A blank number in key=value input denotes an absent scalar.
        if value == "" and spec is not None and spec.value_type is int:
            continue
        values[key] = value
    return values


def get_str(key: str, default: str, *, config_path: Path | str | None = None) -> str:
    spec = MACHINE_SETTING_KEYS.get(key)
    raw = read_all(config_path).get(key)
    if spec is not None:
        value = spec.stored_value(key, raw) if raw is not None else spec.default
        return str(value).lower() if isinstance(value, bool) else str(value)
    return raw if raw is not None else default


def get_int(
    key: str, default: int | None = None, *, config_path: Path | str | None = None
) -> int:
    raw = read_all(config_path).get(key)
    spec = MACHINE_SETTING_KEYS.get(key)
    if spec is not None:
        value = spec.stored_value(key, raw) if raw is not None else spec.default
        return int(value)
    if raw is None or raw == "":
        if default is None:
            raise ValueError(
                f"setting_key_unknown: {key}. Recovery: yoke settings list"
            )
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def get_seconds(
    key: str, default: int, *, config_path: Path | str | None = None
) -> int:
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
