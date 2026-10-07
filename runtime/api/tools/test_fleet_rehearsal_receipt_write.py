"""Fleet rehearsal receipts land on the control plane the caller names."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from runtime.api.tools import fleet_rehearsal_receipt_write as receipt_write
from runtime.api.tools import preflight_fleet_migrations as preflight
from runtime.api.tools.test_migration_admin_selected_readiness import (
    _authority,
    _declare_admin,
    _select_yoke_fleet,
)
from yoke_contracts.machine_config import runtime as machine_config
from yoke_core.domain import connected_env_readiness as readiness
from yoke_core.domain import local_universe, migration_fleet_preflight

_PLATFORM_LOGIN = "platform-prod-registry-db-admin"


def _machine_with_a_second_prod_login(tmp_path: Path, monkeypatch) -> None:
    """A machine holding a prod-flagged database login that is not Yoke's."""
    config = {
        "connections": {
            "prod": {"transport": "https"},
            "prod-db-admin": {"transport": "local-postgres", "prod": True},
            _PLATFORM_LOGIN: {"transport": "local-postgres", "prod": True},
        }
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(path))


def _control_planes(monkeypatch, yoke_planes: set[str]) -> list[tuple[str, str]]:
    """Answer registered commands only on the named Yoke control planes."""
    calls: list[tuple[str, str]] = []

    def run(argv: list[str], **kwargs: Any) -> SimpleNamespace:
        env = kwargs["env"]["YOKE_ENV"]
        calls.append((env, argv[3]))
        if env in yoke_planes:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(
            returncode=1, stdout="", stderr='relation "projects" does not exist'
        )

    monkeypatch.setattr(receipt_write.subprocess, "run", run)
    return calls


def _rehearsal_passes(monkeypatch, tmp_path: Path) -> list[str]:
    rehearsed: list[str] = []

    def rehearse(_dsn_for: Any, **_kwargs: Any) -> list[SimpleNamespace]:
        rehearsed.append("rehearse")
        return [SimpleNamespace(passed=True, line="yoke_alpha: PASS")]

    _declare_admin(monkeypatch, {"prod": "prod-db-admin"})
    _select_yoke_fleet(monkeypatch)
    monkeypatch.setattr(readiness, "activate_selected_postgres", _authority)
    monkeypatch.setattr(
        local_universe, "ensure_engine_binaries", lambda _emit: tmp_path
    )
    monkeypatch.setattr(
        local_universe,
        "cluster_spec",
        lambda **_kwargs: SimpleNamespace(sock_dir=tmp_path / "socket"),
    )
    monkeypatch.setattr(migration_fleet_preflight, "rehearse_fleet", rehearse)
    return rehearsed


def _record(receipt_env: str) -> int:
    return preflight.main(
        [
            "--project",
            "yoke",
            "prod",
            "--record-receipt",
            "--product-sha",
            "abc",
            "--receipt-env",
            receipt_env,
        ]
    )


def test_a_second_prod_login_does_not_stop_the_named_plane_recording(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _machine_with_a_second_prod_login(tmp_path, monkeypatch)
    calls = _control_planes(monkeypatch, {"prod"})
    rehearsed = _rehearsal_passes(monkeypatch, tmp_path)

    assert _record("prod") == 0

    assert rehearsed == ["rehearse"]
    assert calls == [("prod", "get"), ("prod", "merge")]
    assert "receipt recorded on prod covering yoke/prod" in capsys.readouterr().out


def test_a_connection_that_is_not_a_yoke_control_plane_refuses_by_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _machine_with_a_second_prod_login(tmp_path, monkeypatch)
    calls = _control_planes(monkeypatch, {"prod"})
    rehearsed = _rehearsal_passes(monkeypatch, tmp_path)

    assert _record(_PLATFORM_LOGIN) == 2

    refusal = capsys.readouterr().err
    assert (
        f"--receipt-env {_PLATFORM_LOGIN} did not answer as a Yoke control plane"
        in refusal
    )
    assert "yoke/prod" in refusal
    assert 'relation "projects" does not exist' in refusal
    assert "--receipt-env <control-plane>" in refusal
    assert calls == [(_PLATFORM_LOGIN, "get")]
    assert rehearsed == []


def test_a_probe_that_cannot_run_is_a_named_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unrunnable(*_args: Any, **_kwargs: Any) -> None:
        raise subprocess.TimeoutExpired(cmd="yoke", timeout=120)

    monkeypatch.setattr(receipt_write.subprocess, "run", unrunnable)

    refusal = receipt_write.receipt_plane_refusal(
        receipt_env="prod", project="yoke", environment="prod"
    )

    assert refusal.startswith(
        "--receipt-env prod did not answer as a Yoke control plane"
    )
    assert "could not run" in refusal
