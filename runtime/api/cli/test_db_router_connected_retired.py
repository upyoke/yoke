from __future__ import annotations

import io
import json
import os
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from yoke_core.cli import db_router
from yoke_core.domain import machine_config, yoke_connected_env


def _binding(root: Path, dsn_file: Path) -> Path:
    path = root / ".yoke" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "prod-db-admin",
                "connections": {
                    "prod-db-admin": {
                        "transport": "local-postgres",
                        "credential_source": {
                            "kind": "dsn_file",
                            "path": str(dsn_file),
                        },
                    },
                },
                "projects": {
                    str(root.resolve()): {
                        "project_id": 1,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _run(argv: list) -> tuple[int, str, str]:
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = db_router.main(argv)
    return rc, out.getvalue(), err.getvalue()


def test_retired_yoke_db_env_does_not_warn_or_create(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "runtime" / "api" / "cli").mkdir(parents=True)
    fake_file = repo / "runtime" / "api" / "cli" / "db_router.py"
    fake_file.touch()
    main_db = repo / "data" / "yoke.db"
    main_db.parent.mkdir()
    dsn_file = tmp_path / "target.dsn"
    dsn_file.write_text("host=aurora dbname=yoke_prod\n", encoding="utf-8")
    binding = _binding(repo, dsn_file)
    for key in ("YOKE_DB_INIT_DONE", "YOKE_DB_INIT_ALLOW"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(yoke_connected_env.PYTEST_ENABLE_ENV, "1")
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))
    monkeypatch.setenv("YOKE_DB", str(main_db))
    monkeypatch.chdir(repo)
    monkeypatch.setattr(db_router, "__file__", str(fake_file))
    monkeypatch.setattr(db_router, "_dispatch_python_module", lambda *_a: 0)

    rc, out, err = _run(["items", "get", "YOK-1", "status"])

    assert rc == 0
    assert out == ""
    assert err == ""
    assert os.environ["YOKE_DB"] == str(main_db)
    assert not main_db.exists()
