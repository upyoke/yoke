"""API-server logs do not require a selected project or session."""

import json
from pathlib import Path
from types import SimpleNamespace

from yoke_core.tools import api_server


def test_unmapped_start_uses_machine_log(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("YOKE_PROJECT", raising=False)
    monkeypatch.delenv("YOKE_API_LOG", raising=False)
    monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
    monkeypatch.setattr(api_server, "_resolve_repo_root", lambda: tmp_path)
    monkeypatch.setattr(api_server, "_pid_file", lambda: tmp_path / ".pid")
    calls = []
    record = {"pid": 123, "start_time": 1.0, "members": [[123, 1.0]]}

    def launch(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(pid=123, to_record=lambda: record)

    monkeypatch.setattr(api_server, "spawn_group", launch)
    assert api_server.cmd_start() == 0
    assert Path(calls[0]["stdout"].name) == (
        tmp_path / "scratch" / "storage" / "api-server" / "yoke-api-server.log"
    )
    assert json.loads((tmp_path / ".pid").read_text()) == record


def test_explicit_log_override(monkeypatch, tmp_path):
    log = tmp_path / "chosen.log"
    monkeypatch.setenv("YOKE_API_LOG", str(log))
    assert api_server._log_file() == log
