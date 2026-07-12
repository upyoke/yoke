"""Self-host root bootstrap and runtime secret permission contract."""

from __future__ import annotations

import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from yoke_core.api.oidc_config import OIDC_CLIENT_SECRET_FILE_ENV
from yoke_core.domain.db_backend import PG_DSN_FILE_ENV
from yoke_core.domain.github_app_control_plane import (
    GITHUB_APP_PRIVATE_KEY_FILE_ENV,
)
from yoke_core.tools import self_host_secret_materialization
from yoke_core.tools import self_host_server_bootstrap
from yoke_core.api import container_healthcheck
from yoke_core.tools.self_host_server_bootstrap import (
    SelfHostServerBootstrapError,
    assert_no_effective_linux_capabilities,
    assert_runtime_secrets_readable,
    materialize_self_host_runtime_secrets,
)


_SOURCE_NAMES = {
    PG_DSN_FILE_ENV: "yoke-db-dsn",
    OIDC_CLIENT_SECRET_FILE_ENV: "yoke-oidc-client-secret",
    GITHUB_APP_PRIVATE_KEY_FILE_ENV: "yoke-github-app-private-key",
}


def _source_files(source_dir: Path) -> dict[str, str]:
    source_dir.mkdir()
    env = {}
    payloads = {
        PG_DSN_FILE_ENV: b"host=db dbname=yoke user=yoke password=test\n",
        OIDC_CLIENT_SECRET_FILE_ENV: b"oidc-test-secret\n",
        GITHUB_APP_PRIVATE_KEY_FILE_ENV: (
            b"-----BEGIN PRIVATE KEY-----\nZmFrZQ==\n-----END PRIVATE KEY-----\n"
        ),
    }
    for env_name, file_name in _SOURCE_NAMES.items():
        path = source_dir / file_name
        path.write_bytes(payloads[env_name])
        path.chmod(0o600)
        env[env_name] = str(path)
    return env


def test_all_core_secrets_move_to_runtime_owned_private_files(tmp_path: Path):
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "runtime"
    env = _source_files(source_dir)

    rewritten, targets = materialize_self_host_runtime_secrets(
        env,
        source_dir=source_dir,
        target_dir=target_dir,
        runtime_uid=os.geteuid(),
        runtime_gid=os.getegid(),
        expected_source_uid=os.geteuid(),
        require_read_only_sources=False,
    )

    assert set(targets) == {
        target_dir / file_name for file_name in _SOURCE_NAMES.values()
    }
    assert stat.S_IMODE(target_dir.stat().st_mode) == 0o700
    for env_name, source_name in _SOURCE_NAMES.items():
        source = source_dir / source_name
        target = Path(rewritten[env_name])
        assert target.parent == target_dir
        assert target.read_bytes() == source.read_bytes()
        assert stat.S_IMODE(source.stat().st_mode) == 0o600
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
        assert (target.stat().st_uid, target.stat().st_gid) == (
            os.geteuid(),
            os.getegid(),
        )
    assert_runtime_secrets_readable(targets)


def test_linux_effective_capability_proof_is_fail_closed(tmp_path: Path):
    status = tmp_path / "status"
    status.write_text("Name:\ttest\nCapEff:\t0000000000000000\n", encoding="utf-8")
    assert_no_effective_linux_capabilities(status_path=status)

    status.write_text("Name:\ttest\nCapEff:\t0000000000000001\n", encoding="utf-8")
    with pytest.raises(SelfHostServerBootstrapError, match="retained effective"):
        assert_no_effective_linux_capabilities(status_path=status)


def test_compose_healthcheck_drops_root_before_running_probe(monkeypatch):
    calls = []
    monkeypatch.setattr(self_host_server_bootstrap.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        self_host_server_bootstrap.pwd,
        "getpwnam",
        lambda _name: SimpleNamespace(pw_uid=100, pw_gid=101),
    )
    monkeypatch.setattr(
        self_host_server_bootstrap,
        "drop_to_self_host_runtime_identity",
        lambda **identity: calls.append(("drop", identity)),
    )
    monkeypatch.setattr(
        self_host_server_bootstrap,
        "assert_no_effective_linux_capabilities",
        lambda: calls.append(("capabilities", {})),
    )
    monkeypatch.setattr(
        container_healthcheck,
        "main",
        lambda: calls.append(("healthcheck", {})) or 0,
    )

    assert self_host_server_bootstrap.main(["--healthcheck"]) == 0
    assert calls == [
        ("drop", {"uid": 100, "gid": 101}),
        ("capabilities", {}),
        ("healthcheck", {}),
    ]


def test_native_permission_model_requires_runtime_owned_copy():
    host_source = (0o100600, 501, 20)
    runtime_copy = (0o100600, 100, 101)

    assert not _identity_can_read(host_source, uid=100, gids={101})
    assert _identity_can_read(runtime_copy, uid=100, gids={101})


def test_compose_normalized_mode_requires_read_only_mount_and_sealed_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "runtime"
    env = _source_files(source_dir)
    for path in source_dir.iterdir():
        path.chmod(0o755)
    checked = []
    monkeypatch.setattr(
        self_host_secret_materialization,
        "_assert_read_only_source_mount",
        lambda path: checked.append(path.name),
    )

    _rewritten, targets = materialize_self_host_runtime_secrets(
        env,
        source_dir=source_dir,
        target_dir=target_dir,
        runtime_uid=os.geteuid(),
        runtime_gid=os.getegid(),
        expected_source_uid=os.geteuid(),
        require_read_only_sources=True,
    )

    assert set(checked) == set(_SOURCE_NAMES.values())
    assert stat.S_IMODE(source_dir.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in targets)


def test_bootstrap_rejects_non_allowlisted_or_weak_source(tmp_path: Path):
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "runtime"
    env = _source_files(source_dir)
    env[PG_DSN_FILE_ENV] = str(source_dir / "another-dsn")

    with pytest.raises(SelfHostServerBootstrapError, match="allowlisted"):
        materialize_self_host_runtime_secrets(
            env,
            source_dir=source_dir,
            target_dir=target_dir,
            runtime_uid=os.geteuid(),
            runtime_gid=os.getegid(),
            expected_source_uid=os.geteuid(),
            require_read_only_sources=False,
        )

    env = _source_files(tmp_path / "weak-source")
    Path(env[PG_DSN_FILE_ENV]).chmod(0o640)
    with pytest.raises(SelfHostServerBootstrapError, match="root-only"):
        materialize_self_host_runtime_secrets(
            env,
            source_dir=tmp_path / "weak-source",
            target_dir=tmp_path / "weak-target",
            runtime_uid=os.geteuid(),
            runtime_gid=os.getegid(),
            expected_source_uid=os.geteuid(),
            require_read_only_sources=False,
        )


def _identity_can_read(
    file_state: tuple[int, int, int],
    *,
    uid: int,
    gids: set[int],
) -> bool:
    mode, owner_uid, owner_gid = file_state
    if uid == owner_uid:
        return bool(mode & stat.S_IRUSR)
    if owner_gid in gids:
        return bool(mode & stat.S_IRGRP)
    return bool(mode & stat.S_IROTH)
