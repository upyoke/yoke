"""Engine doubles and machine homes for local-universe CLI tests."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_cli.config import local_universe_setup as setup


class _EngineError(RuntimeError):
    pass


def _stub_engine(
    *,
    born: bool = True,
    dsn: str = "host=/sock user=yoke dbname=yoke",
    socket_dsn_aliases: tuple[str, ...] = (),
):
    report = {
        "born": born,
        "cluster": {"root": "/machine-home/local-universe", "running": True},
        "dsn": dsn,
        "socket_dsn_aliases": list(socket_dsn_aliases),
        "org": {"slug": "default", "name": "Default Org"},
        "human_actor_id": 1,
    }
    if born:
        report["verified"] = {"organizations": 1, "actors": 1}
    return SimpleNamespace(
        birth=lambda org_name, emit: dict(report),
        start=lambda emit: {"running": True},
        stop=lambda: {"running": False},
        status=lambda: {"running": False, "initialized": True},
        LocalUniverseError=_EngineError,
    )


@pytest.fixture()
def machine_home(monkeypatch, tmp_path) -> Path:
    home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    monkeypatch.setattr(setup, "_record_operating_actor", lambda report, path: None)
    return home


def _config(home: Path) -> dict:
    return json.loads((home / "config.json").read_text(encoding="utf-8"))
