"""Service-client connected-env regressions for the hard Postgres cutover."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain import machine_config, yoke_connected_env
from yoke_core.api import main_db
from yoke_core.api import service_client_shared_io as io

_RETIRED_BACKEND_ENV = "YOKE_" + "BACKEND"


def _write_binding(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
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
  },
  "projects": {
    "__ROOT__": {"project_id": 1}
  },
  "settings": {
    "executor_default_lane_codex*": "ALTMAN"
  }
}
""".strip().replace("__ROOT__", str(root.resolve())),
        encoding="utf-8",
    )
    return binding


def test_load_routing_config_does_not_require_sqlite_db_under_connected_env(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "repo"
    binding = _write_binding(root)
    monkeypatch.setattr(io, "_repo_root", str(root))
    monkeypatch.setenv(yoke_connected_env.PYTEST_ENABLE_ENV, "1")
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))
    monkeypatch.delenv("YOKE_DB", raising=False)
    monkeypatch.delenv("YOKE_PG_DSN", raising=False)
    monkeypatch.delenv("YOKE_PG_DSN_FILE", raising=False)

    routing = io._load_routing_config()

    assert routing.default_lane_for_executor("codex-desktop") == "ALTMAN"


def test_subprocess_backend_env_uses_pytest_checkout_binding(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    binding = _write_binding(root)
    monkeypatch.setattr(io, "_repo_root", str(root))
    monkeypatch.chdir(root)
    monkeypatch.setenv(yoke_connected_env.PYTEST_ENABLE_ENV, "1")
    monkeypatch.setenv(machine_config.CONFIG_FILE_ENV, str(binding))
    monkeypatch.delenv("YOKE_DB", raising=False)
    monkeypatch.delenv("YOKE_PG_DSN", raising=False)
    monkeypatch.delenv("YOKE_PG_DSN_FILE", raising=False)

    env = io._subprocess_backend_env()

    assert env[machine_config.CONFIG_FILE_ENV] == str(binding)
    assert _RETIRED_BACKEND_ENV not in env
    assert Path(env["YOKE_PG_DSN_FILE"]).resolve() == root / ".secret.dsn"


def test_api_config_path_does_not_require_sqlite_db(monkeypatch, tmp_path: Path) -> None:
    config = tmp_path / ".yoke" / "config"
    config.parent.mkdir()
    config.write_text("executor_default_lane_codex*=ALTMAN\n", encoding="utf-8")

    def boom():
        raise RuntimeError("SQLite authority retired")

    monkeypatch.setattr(main_db, "get_db_path", boom)
    monkeypatch.setattr(
        "yoke_core.domain.worktree_paths.resolve_named_path",
        lambda mode, cwd: str(config),
    )

    assert main_db.get_config_path() == config.resolve()
