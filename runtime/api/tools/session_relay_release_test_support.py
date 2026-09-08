"""Shared machine-config and subprocess doubles for relay release tests.

The release tests and the refusal tests both need one configured relay
instance whose state lives under a temporary directory, so the builders live
here rather than in either module.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from yoke_cli.config.session_relay_instance import RelayInstance, resolve_relay_instance


RELEASE = "0.1.1+launch.365"
NEXT_RELEASE = "0.1.1+launch.366"
DEFAULT_API_URL = "https://relay.example.test/api"


def write_relay_config(tmp_path: Path, api_url: str = DEFAULT_API_URL) -> Path:
    """One prod https connection, written where a relay install would read it."""
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "prod",
                "connections": {
                    "prod": {
                        "transport": "https",
                        "prod": True,
                        "api_url": api_url,
                        "credential_source": {
                            "kind": "token_file",
                            "path": str(tmp_path / "token"),
                        },
                    }
                },
                "projects": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def relay_instance(tmp_path: Path, api_url: str = DEFAULT_API_URL) -> RelayInstance:
    return resolve_relay_instance(
        config_path=write_relay_config(tmp_path, api_url),
        environment="prod",
        yoke_home=tmp_path / "state",
    )


def fake_venv(path: Path) -> None:
    binary = path / "bin"
    binary.mkdir(parents=True)
    (binary / "python").touch()
    (binary / "yoke").write_text(f"#!{binary / 'python'}\n", encoding="utf-8")


def runner_for(release: str, calls: list[list[str]]):
    """A pip/verify runner that reports the release it was asked to install."""

    def run(command, **_kwargs):
        argv = list(command)
        calls.append(argv)
        stdout = f"{release}\n" if "-c" in argv else ""
        return subprocess.CompletedProcess(argv, 0, stdout, "")

    return run


__all__ = [
    "DEFAULT_API_URL",
    "NEXT_RELEASE",
    "RELEASE",
    "fake_venv",
    "relay_instance",
    "runner_for",
    "write_relay_config",
]
