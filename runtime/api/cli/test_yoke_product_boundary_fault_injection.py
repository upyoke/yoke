"""Fault-injection tests for the installable Yoke product CLI boundary."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from runtime.api.product_boundary_isolation import write_sitecustomize


REPO_ROOT = Path(__file__).resolve().parents[3]
CLI_SRC = REPO_ROOT / "packages" / "yoke-cli" / "src"
CONTRACTS_SRC = REPO_ROOT / "packages" / "yoke-contracts" / "src"
HARNESS_SRC = REPO_ROOT / "packages" / "yoke-harness" / "src"
CLIENT_PYTHONPATH = os.pathsep.join(
    (str(CLI_SRC), str(CONTRACTS_SRC), str(HARNESS_SRC)),
)
FORBIDDEN_AUTHORITY_IMPORTS = (
    "yoke_core",
    "runtime.api",
    "runtime.harness",
    "psycopg",
    "psycopg2",
)
BOUNDARY_MARKER = "__YOKE_PRODUCT_BOUNDARY__"

_FORBIDDEN_JSON = json.dumps(FORBIDDEN_AUTHORITY_IMPORTS)
_HARNESS = (
    "import importlib.abc\n"
    "import json\n"
    "import os\n"
    "import sys\n"
    "import traceback\n"
    f"FORBIDDEN = tuple(json.loads({_FORBIDDEN_JSON!r}))\n"
    r"""
blocked_attempts = []

def _is_forbidden(fullname):
    return any(
        fullname == name or fullname.startswith(name + ".")
        for name in FORBIDDEN
    )

class ProductBoundaryBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if _is_forbidden(fullname):
            blocked_attempts.append(fullname)
            raise ImportError(
                "blocked forbidden product-boundary import: " + fullname
            )
        return None

sys.meta_path.insert(0, ProductBoundaryBlocker())
rc = 1
caught = None
try:
    from yoke_cli.main import main

    rc = main(sys.argv[1:])
    rc = int(rc or 0)
except SystemExit as exc:
    rc = exc.code if isinstance(exc.code, int) else 1
except Exception as exc:
    caught = {"type": type(exc).__name__, "message": str(exc)}
    traceback.print_exc(file=sys.stderr)
finally:
    forbidden_loaded = sorted(
        name for name in sys.modules
        if _is_forbidden(name)
    )
    payload = {
        "blocked_attempts": blocked_attempts,
        "caught": caught,
        "cwd": os.getcwd(),
        "forbidden_loaded": forbidden_loaded,
        "home": os.environ.get("HOME", ""),
        "pythonpath": os.environ.get("PYTHONPATH", "").split(os.pathsep),
        "yoke_config": os.environ.get("YOKE_CONFIG", ""),
        "yoke_machine_config_file": os.environ.get(
            "YOKE_MACHINE_CONFIG_FILE", ""
        ),
        "yoke_machine_home": os.environ.get("YOKE_MACHINE_HOME", ""),
    }
    print(
        "__YOKE_PRODUCT_BOUNDARY__" + json.dumps(payload, sort_keys=True),
        file=sys.stderr,
    )
sys.exit(rc)
"""
)


@dataclass(frozen=True)
class ProductCliRun:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    boundary: Mapping[str, object]


def _run_product_cli(
    tmp_path: Path,
    args: Sequence[str],
    *,
    config_payload: Mapping[str, object] | None = None,
    include_harness: bool = True,
    stdin_data: str = "",
    client_cwd: Path | None = None,
) -> ProductCliRun:
    home = tmp_path / "home"
    yoke_home = home / ".yoke"
    client_cwd = client_cwd or tmp_path / "client-cwd"
    yoke_home.mkdir(parents=True, exist_ok=True)
    client_cwd.mkdir(parents=True, exist_ok=True)
    config_path = yoke_home / "config.json"
    if config_payload is not None:
        config_path.write_text(json.dumps(config_payload) + "\n", encoding="utf-8")
    pythonpath = (
        CLIENT_PYTHONPATH
        if include_harness
        else os.pathsep.join((str(CLI_SRC), str(CONTRACTS_SRC)))
    )
    allowed_paths = (
        (CLI_SRC, CONTRACTS_SRC, HARNESS_SRC)
        if include_harness
        else (CLI_SRC, CONTRACTS_SRC)
    )
    sitecustomize_dir = write_sitecustomize(
        tmp_path,
        repo_root=REPO_ROOT,
        allowed_repo_paths=allowed_paths,
    )
    env = {
        "HOME": str(home),
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPATH": os.pathsep.join((str(sitecustomize_dir), pythonpath)),
        "YOKE_CONFIG": str(config_path),
        "YOKE_MACHINE_CONFIG_FILE": str(config_path),
        "YOKE_MACHINE_HOME": str(yoke_home),
    }
    result = subprocess.run(
        [sys.executable, "-c", _HARNESS, *args],
        cwd=client_cwd,
        env=env,
        text=True,
        input=stdin_data,
        capture_output=True,
        timeout=20,
        check=False,
    )
    stderr, boundary = _extract_boundary(result.stderr)
    return ProductCliRun(
        args=tuple(args),
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=stderr,
        boundary=boundary,
    )


def _extract_boundary(stderr: str) -> tuple[str, Mapping[str, object]]:
    lines = stderr.splitlines()
    for index in range(len(lines) - 1, -1, -1):
        line = lines[index]
        if line.startswith(BOUNDARY_MARKER):
            payload = json.loads(line[len(BOUNDARY_MARKER):])
            del lines[index]
            return "\n".join(lines), payload
    raise AssertionError(f"missing boundary marker in stderr:\n{stderr}")


def _assert_clean_client_boundary(run: ProductCliRun) -> None:
    assert run.boundary["caught"] is None, run.stderr
    assert run.boundary["blocked_attempts"] == []
    assert run.boundary["forbidden_loaded"] == []
    assert _repo_pythonpath(run) == [str(CLI_SRC), str(CONTRACTS_SRC), str(HARNESS_SRC)]
    assert not Path(str(run.boundary["cwd"])).resolve().is_relative_to(REPO_ROOT)
    assert Path(str(run.boundary["home"])).name == "home"
    assert str(run.boundary["yoke_config"]).endswith("/home/.yoke/config.json")
    assert (
        run.boundary["yoke_config"]
        == run.boundary["yoke_machine_config_file"]
    )


def _repo_pythonpath(run: ProductCliRun) -> list[str]:
    paths = []
    for raw in run.boundary["pythonpath"]:
        resolved = Path(str(raw)).resolve()
        if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
            paths.append(str(resolved))
    return paths


def test_version_does_not_import_source_authority(tmp_path: Path) -> None:
    run = _run_product_cli(tmp_path, ["--version"])

    assert run.returncode == 0
    assert run.stdout.strip() == "source"
    assert run.stderr == ""
    _assert_clean_client_boundary(run)


def test_top_level_help_does_not_import_source_authority(tmp_path: Path) -> None:
    run = _run_product_cli(tmp_path, ["--help"])

    assert run.returncode == 0
    assert "Available subcommands" in run.stdout
    assert "yoke status" in run.stdout
    assert "yoke project install" in run.stdout
    assert run.stderr == ""
    _assert_clean_client_boundary(run)


def test_status_missing_config_reports_locally_without_authority_import(
    tmp_path: Path,
) -> None:
    run = _run_product_cli(tmp_path, ["status", "--json"])

    assert run.returncode == 1
    report = json.loads(run.stdout)
    assert report["ok"] is False
    assert report["repo_root"] == run.boundary["cwd"]
    issue_codes = {issue["code"] for issue in report["issues"]}
    assert "config_missing" in issue_codes
    assert "connections_required" in issue_codes
    assert set(report["runtime"]["package_versions"].values()) == {""}
    assert run.stderr == ""
    _assert_clean_client_boundary(run)


def test_product_local_help_commands_do_not_import_source_authority(
    tmp_path: Path,
) -> None:
    commands = (
        (("db", "read", "--help"), "usage: yoke db read"),
        (("onboard", "--help"), "usage: yoke onboard"),
        (("project", "install", "--help"), "usage: yoke project install"),
        (("dev", "setup", "--help"), "usage: yoke dev setup"),
        (
            ("dev", "path-snapshot-prewarm", "--help"),
            "usage: yoke dev path-snapshot-prewarm",
        ),
        (
            ("readiness", "prd-validate", "--help"),
            "usage: yoke readiness prd-validate",
        ),
    )

    for args, expected_usage in commands:
        run = _run_product_cli(tmp_path / "-".join(args), args)
        assert run.returncode == 0
        assert expected_usage in run.stdout
        assert run.stderr == ""
        _assert_clean_client_boundary(run)


def test_db_read_dispatch_fails_closed_at_existing_local_boundary(
    tmp_path: Path,
) -> None:
    run = _run_product_cli(tmp_path, ["db", "read", "SELECT 1", "--json"])

    assert run.returncode == 1
    response = json.loads(run.stdout)
    assert response["function"] == "db.read.run"
    assert response["success"] is False
    assert response["error"]["code"] == "local_postgres_core_unavailable"
    assert any(
        name == "yoke_core" or str(name).startswith("yoke_core.")
        for name in run.boundary["blocked_attempts"]
    )
    assert run.boundary["forbidden_loaded"] == []
    assert run.boundary["caught"] is None


def test_db_read_prod_flagged_local_postgres_requires_core_import(
    tmp_path: Path,
) -> None:
    run = _run_product_cli(
        tmp_path,
        ["db", "read", "SELECT 1", "--json"],
        config_payload={
            "schema_version": 1,
            "active_env": "prod-db-admin",
            "connections": {
                "prod-db-admin": {
                    "transport": "local-postgres",
                    "prod": True,
                },
            },
        },
    )

    assert run.returncode == 1
    response = json.loads(run.stdout)
    assert response["function"] == "db.read.run"
    assert response["success"] is False
    assert response["error"]["code"] == "local_postgres_core_unavailable"
    assert "yoke-core engine" in response["error"]["message"]
    assert any(
        name == "yoke_core" or str(name).startswith("yoke_core.")
        for name in run.boundary["blocked_attempts"]
    )
    assert run.boundary["forbidden_loaded"] == []
    assert run.boundary["caught"] is None


def test_local_only_dispatch_fails_closed_when_core_authority_is_blocked(
    tmp_path: Path,
) -> None:
    run = _run_product_cli(tmp_path, ["agents", "render", "--json"])

    assert run.returncode == 1
    response = json.loads(run.stdout)
    assert response["success"] is False
    assert response["error"]["code"] == "local_postgres_core_unavailable"
    assert "yoke-core engine" in response["error"]["message"]
    assert "yoke env use" in response["error"]["recovery_hint"]
    assert any(
        name == "yoke_core" or str(name).startswith("yoke_core.")
        for name in run.boundary["blocked_attempts"]
    )
    assert run.boundary["forbidden_loaded"] == []
    assert run.boundary["caught"] is None
    assert "Traceback" not in run.stderr


def test_ordinary_packaged_refresh_does_not_import_core(
    tmp_path: Path,
) -> None:
    target = tmp_path / "external-project"
    target.mkdir()
    run = _run_product_cli(
        tmp_path,
        [
            "project", "refresh", str(target), "--project-id", "7",
            "--config", str(tmp_path / "home/.yoke/config.json"),
        ],
        config_payload={
            "schema_version": 1,
            "active_env": "product",
            "connections": {
                "product": {
                    "transport": "https",
                    "api_url": "http://127.0.0.1:1",
                    "credential_source": {
                        "kind": "token_env",
                        "env_var": "YOKE_TEST_TOKEN",
                    },
                },
            },
        },
    )

    assert run.returncode == 1
    assert "yoke_core" not in run.boundary["blocked_attempts"]
    assert not any(
        str(name).startswith("yoke_core.")
        for name in run.boundary["blocked_attempts"]
    )
    assert run.boundary["forbidden_loaded"] == []
    assert not (target / ".yoke/install-manifest.json").exists()


def test_status_fails_when_hook_runtime_package_is_missing(
    tmp_path: Path,
) -> None:
    run = _run_product_cli(
        tmp_path,
        ["status", "--json"],
        include_harness=False,
    )

    report = json.loads(run.stdout)
    assert run.returncode == 1
    assert any(
        issue["code"] == "import_missing"
        and "yoke_harness" in issue["message"]
        for issue in report["issues"]
    )


def test_source_refresh_preview_diagnoses_without_hook_runtime(
    tmp_path: Path,
) -> None:
    target = tmp_path / "external-project"
    target.mkdir()
    run = _run_product_cli(
        tmp_path,
        [
            "project", "refresh", str(target),
            "--source-checkout", str(REPO_ROOT),
            "--project-id", "8",
            "--project-slug", "preview-project",
            "--json",
        ],
        include_harness=False,
    )

    assert run.returncode == 0, run.stderr
    report = json.loads(run.stdout)
    assert report["preview"] is True
    assert report["target_writes"] is False
    assert run.boundary["blocked_attempts"] == []
    assert run.boundary["forbidden_loaded"] == []
    assert not (target / ".yoke/install-manifest.json").exists()
