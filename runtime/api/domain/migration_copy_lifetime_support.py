"""Real rehearsal fixtures: CI's declared service, or a local scratch server."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

from yoke_core.domain import db_backend, postgres_cluster
from runtime.api.domain.test_migration_fleet_preflight_extension_restore import (
    _server_bin_dir,
)


def wait_until(predicate):
    deadline = time.monotonic() + 15
    while not predicate():
        assert time.monotonic() < deadline, "copy lifetime barrier timed out"
        time.sleep(0.01)


def _service_spec(socket_dir):
    # Prove the socket reaches the *same* server as the declared CI DSN.
    # A separate host initdb server would not exercise the selected substrate.
    with db_backend.connect_psycopg(os.environ[db_backend.PG_DSN_ENV]) as conn:
        user, version, identity = conn.execute(
            "SELECT current_user, current_setting('server_version_num')::int, "
            "system_identifier FROM pg_control_system()"
        ).fetchone()
    major = version // 10000
    candidates = [Path(f"/usr/lib/postgresql/{major}/bin")]
    on_path = shutil.which("pg_dump")
    if on_path:
        candidates.append(Path(on_path).parent)
    for candidate in candidates:
        executable = candidate / "pg_dump"
        if not executable.exists():
            continue
        result = subprocess.run(
            [str(executable), "--version"], capture_output=True, text=True, check=True
        )
        if result.stdout.split()[2].split(".")[0] == str(major):
            break
    else:
        pytest.fail(f"copy lifetime proof requires PostgreSQL {major} client tools")
    spec = postgres_cluster.ClusterSpec(
        Path(socket_dir), user, socket_dir=Path(socket_dir), bin_dir=candidate
    )
    with db_backend.connect_psycopg(postgres_cluster.dsn(spec)) as conn:
        assert (
            conn.execute(
                "SELECT system_identifier FROM pg_control_system()"
            ).fetchone()[0]
            == identity
        )
    return spec


@pytest.fixture(scope="module", name="copy_cluster")
def copy_cluster():
    """No skips: the real kernel and transfer clients must reach PostgreSQL."""
    socket_dir = os.environ.get("YOKE_PG_SOCKET_DIR")
    if os.environ.get("CI") or socket_dir:
        assert socket_dir, "CI must expose its declared Postgres service socket"
        yield _service_spec(socket_dir)
        return  # CI owns the service; tests drop only their own databases.
    bin_dir, searched = _server_bin_dir()
    assert bin_dir is not None, (
        f"copy lifetime proof requires initdb; searched {searched}"
    )
    with tempfile.TemporaryDirectory(prefix="yoke-copy-lock-", dir="/tmp") as scratch:
        spec = postgres_cluster.ClusterSpec(
            Path(scratch),
            "copyfixture",
            bin_dir=bin_dir,
            server_settings=(("fsync", "off"),),
            stop_mode="immediate",
        )
        try:
            assert postgres_cluster.ensure_started(spec) == 0
            yield spec
        finally:
            postgres_cluster.destroy(spec)
