"""Regressions for hook lifecycle children under connected Postgres authority."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from yoke_core.domain import machine_config, yoke_connected_env
from runtime.harness.hook_runner import service_client, target

_RETIRED_BACKEND_ENV = "YOKE_" + "BACKEND"


def test_target_service_client_path_falls_back_to_yoke_code_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    yoke_root = tmp_path / "yoke"
    service_path = yoke_root / "runtime" / "api" / "service_client.py"
    service_path.parent.mkdir(parents=True)
    service_path.write_text("# service client placeholder\n", encoding="utf-8")
    external_root = tmp_path / "buzz"
    external_root.mkdir()
    monkeypatch.setenv("YOKE_CODE_ROOT", str(yoke_root))

    assert target.target_service_client_path(str(external_root)) == str(service_path)


def _write_machine_config(root: Path) -> Path:
    dsn = root / ".secret.dsn"
    dsn.write_text("postgresql://user:pass@127.0.0.1:6547/yoke_prod\n", encoding="utf-8")
    binding_dir = root / ".yoke"
    binding_dir.mkdir(parents=True, exist_ok=True)
    binding = binding_dir / "config.json"
    binding.write_text(
        """
{
  "schema_version": 1,
  "active_env": "prod-db-admin",
  "connections": {
    "prod-db-admin": {
      "transport": "local-postgres",
      "credential_source": {"kind": "dsn_file", "path": "../.secret.dsn"}
    }
  }
}
""".strip(),
        encoding="utf-8",
    )
    return binding


def test_register_session_child_inherits_target_cwd_and_connected_env(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "repo"
    service_path = root / "runtime" / "api" / "service_client.py"
    service_path.parent.mkdir(parents=True)
    service_path.write_text("# service client placeholder\n", encoding="utf-8")
    binding = _write_machine_config(root)
    monkeypatch.setenv(yoke_connected_env.PYTEST_ENABLE_ENV, "1")
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))

    calls: list[dict[str, Any]] = []

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        calls.append({"cmd": cmd, **kwargs})
        return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")

    monkeypatch.setattr(service_client.subprocess, "run", fake_run)

    err = service_client.register_session(
        str(service_path),
        "sid",
        "codex",
        "openai",
        "gpt-5",
        str(root),
        "codex-desktop",
    )

    assert err is None
    assert calls
    call = calls[0]
    env = call["env"]
    assert call["cwd"] == str(root)
    assert env["YOKE_ROOT"] == str(root)
    assert env[machine_config.CONFIG_FILE_ENV] == str(binding)
    assert _RETIRED_BACKEND_ENV not in env
    assert Path(env["YOKE_PG_DSN_FILE"]).resolve() == root / ".secret.dsn"
    assert env["PYTHONPATH"].split(os.pathsep)[0] == str(root)


def test_register_session_child_imports_yoke_code_for_external_target(
    tmp_path: Path,
    monkeypatch,
) -> None:
    yoke_root = tmp_path / "yoke"
    service_path = yoke_root / "runtime" / "api" / "service_client.py"
    service_path.parent.mkdir(parents=True)
    service_path.write_text("# service client placeholder\n", encoding="utf-8")
    external_root = tmp_path / "buzz"
    external_root.mkdir()
    binding = _write_machine_config(external_root)
    monkeypatch.setenv(yoke_connected_env.PYTEST_ENABLE_ENV, "1")
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))

    calls: list[dict[str, Any]] = []

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        calls.append({"cmd": cmd, **kwargs})
        return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")

    monkeypatch.setattr(service_client.subprocess, "run", fake_run)

    err = service_client.register_session(
        str(service_path),
        "sid",
        "claude",
        "anthropic",
        "opus",
        str(external_root),
        "claude-desktop",
    )

    assert err is None
    call = calls[0]
    env = call["env"]
    pythonpath = env["PYTHONPATH"].split(os.pathsep)
    assert call["cwd"] == str(external_root)
    assert env["YOKE_ROOT"] == str(external_root)
    assert pythonpath[:2] == [str(yoke_root), str(external_root)]


def test_touch_session_uses_same_target_authority(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "repo"
    service_path = root / "runtime" / "api" / "service_client.py"
    service_path.parent.mkdir(parents=True)
    service_path.write_text("# service client placeholder\n", encoding="utf-8")
    binding = _write_machine_config(root)
    monkeypatch.setenv(yoke_connected_env.PYTEST_ENABLE_ENV, "1")
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))
    captured: dict[str, Any] = {}

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        captured.update({"cmd": cmd, **kwargs})
        return subprocess.CompletedProcess(cmd, 0, stdout="{}", stderr="")

    monkeypatch.setattr(service_client.subprocess, "run", fake_run)

    assert service_client.touch_session(str(service_path), str(root), "sid") == 0
    assert captured["cwd"] == str(root)
    assert _RETIRED_BACKEND_ENV not in captured["env"]
    assert captured["cmd"][-2:] == ["--session-id", "sid"]
