"""Opt-in built-image smoke for the self-host portability boundary."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

import psycopg
import pytest

from runtime.api.fixtures import pg_testdb
from yoke_cli.commands import self_host_import
from yoke_cli.self_host import bundle
from yoke_core.domain.api_tokens import bootstrap_admin_token
from yoke_core.domain.environment_bootstrap import run_init_chain_at_dsn
from yoke_core.domain.universe_portability import dump_universe


IMAGE_ENV = "YOKE_TEST_SELF_HOST_IMAGE"


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@pytest.mark.skipif(not os.environ.get(IMAGE_ENV), reason=f"set {IMAGE_ENV}")
def test_built_image_restores_archive_and_issues_usable_token(tmp_path, capsys):
    image = os.environ[IMAGE_ENV]
    source_name = pg_testdb.create_test_database()
    source_dsn = pg_testdb.dsn_for_test_database(source_name)
    docker_parent = Path.home() / ".yoke" / "tmp" / "container-smokes"
    docker_parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    docker_root = Path(
        tempfile.mkdtemp(prefix="yoke-container-smoke-", dir=docker_parent)
    )
    directory = docker_root / "self-host"
    archive = tmp_path / "portable.dump"
    try:
        run_init_chain_at_dsn(source_dsn, emit=lambda _line: None)
        with psycopg.connect(source_dsn) as source:
            bootstrap_admin_token(source)
        dump_universe(source_dsn, archive)
        archive.chmod(0o600)
        bundle.write_bundle(
            directory=str(directory),
            image=image,
            port=_free_port(),
        )
        capsys.readouterr()

        assert (
            self_host_import.self_host_import(
                [str(archive), "--dir", str(directory), "--json"]
            )
            == 0
        )
        payload = json.loads(capsys.readouterr().out)
        raw_token = str(payload["raw_token"])
        assert raw_token.startswith("yoke_v1_")

        verification = subprocess.run(
            (
                "docker",
                "compose",
                "run",
                "--rm",
                "-T",
                "--entrypoint",
                "python",
                "core",
                "-c",
                "import sys; from yoke_core.domain.db_helpers import connect; "
                "from yoke_core.domain.api_tokens import verify_token; "
                "conn=connect(); verified=verify_token(conn, sys.stdin.read().strip()); "
                "print(verified.name); conn.close()",
            ),
            cwd=directory,
            input=raw_token.encode(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert verification.returncode == 0, verification.stderr.decode(
            "utf-8", errors="replace"
        )[-2000:]
        assert verification.stdout.decode().strip() == "self-host-import-admin"
    finally:
        subprocess.run(
            ("docker", "compose", "down", "--volumes", "--remove-orphans"),
            cwd=directory if directory.is_dir() else tmp_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        pg_testdb.drop_test_database(source_name)
        shutil.rmtree(docker_root, ignore_errors=True)
