"""Git credential-helper entrypoint backed by Yoke machine GitHub config.

This module is intentionally self-contained. Source-dev onboarding copies it
into site-packages as a stable helper file before the deferred editable install
repoints package imports at the cloned checkout.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, TextIO


def main(
    argv: list[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m yoke_cli.config.github_git_credential_helper",
    )
    parser.add_argument("--config", dest="config_path", default=None)
    parser.add_argument("--token-kind", dest="token_kind", default="")
    parser.add_argument("operation", nargs="?", default="")
    parsed = parser.parse_args(sys.argv[1:] if argv is None else list(argv))
    if parsed.operation != "get":
        return 0
    fields = _read_fields(stdin or sys.stdin)
    if fields.get("protocol") != "https" or fields.get("host") != "github.com":
        return 0
    token = _read_machine_token(parsed.config_path, parsed.token_kind)
    if not token:
        return 0
    out = stdout or sys.stdout
    print("username=x-access-token", file=out)
    print(f"password={token}", file=out)
    return 0


def _read_fields(stream: TextIO) -> dict[str, str]:
    fields: dict[str, str] = {}
    for raw in stream:
        line = raw.rstrip("\n")
        if not line:
            break
        key, separator, value = line.partition("=")
        if separator:
            fields[key] = value
    return fields


def _read_machine_token(
    config_path: str | Path | None,
    token_kind: str,
) -> str | None:
    if config_path is None or not token_kind:
        return None
    try:
        payload = _load_config(config_path)
    except (OSError, ValueError):
        return None
    github = payload.get("github") if isinstance(payload, dict) else None
    source = github.get("credential_source") if isinstance(github, dict) else None
    if not isinstance(source, Mapping):
        return None
    if str(source.get("kind") or "") != token_kind:
        return None
    raw_path = str(source.get("path") or "").strip()
    if not raw_path:
        return None
    try:
        token = _machine_path(raw_path).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return token or None


def _load_config(config_path: str | Path | None) -> dict[str, Any]:
    if config_path is None:
        return {}
    selected = Path(config_path).expanduser()
    if not selected.is_file():
        return {}
    payload = json.loads(selected.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}
    return payload


def _machine_path(raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    return path


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["main"]
