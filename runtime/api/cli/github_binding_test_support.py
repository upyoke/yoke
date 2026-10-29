"""Shared config and observed authority for GitHub binding write tests."""

from contextlib import contextmanager
import json
from pathlib import Path
from threading import Event, Thread, current_thread
from types import SimpleNamespace

import pytest
from yoke_cli.config import machine_config_file, writer


def _two_service_config(tmp_path: Path) -> Path:
    token = tmp_path / "actor.token"
    token.write_text("actor-token\n", encoding="utf-8")
    token.chmod(0o600)
    config = tmp_path / "machine-home" / "config.json"
    config.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    def connection(name: str) -> dict[str, object]:
        return {
            "transport": "https",
            "protected": False,
            "api_url": f"https://{name}.yoke.example/v1",
            "credential_source": {
                "kind": "token_file",
                "path": str(token),
            },
        }

    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "service-a",
                "connections": {
                    "service-a": connection("service-a"),
                    "service-b": connection("service-b"),
                },
            }
        ),
        encoding="utf-8",
    )
    config.chmod(0o600)
    return config


def _install_observed_authority(
    monkeypatch: pytest.MonkeyPatch,
    config: Path,
    target: object,
) -> tuple[Event, Event, list[Thread]]:
    attempted = Event()
    switched = Event()
    threads: list[Thread] = []
    real_operation_lock = machine_config_file.exclusive_lock

    @contextmanager
    def observed_operation_lock(path=None):
        if current_thread().name == "github-destination-switch":
            attempted.set()
        with real_operation_lock(path):
            yield

    monkeypatch.setattr(
        machine_config_file,
        "exclusive_lock",
        observed_operation_lock,
    )

    @contextmanager
    def locked_authority(*_args, **_kwargs):
        with machine_config_file.exclusive_lock(config):
            yield SimpleNamespace(
                api_url="https://api.github.com",
                token=SimpleNamespace(access_token="service-a-user-token"),
            )

    monkeypatch.setattr(
        target,
        "locked_profile_bound_access_for_binding",
        locked_authority,
    )

    def switch_destination() -> None:
        writer.set_active_env("service-b", path=config)
        switched.set()

    threads.append(
        Thread(
            target=switch_destination,
            name="github-destination-switch",
            daemon=True,
        )
    )
    return attempted, switched, threads
