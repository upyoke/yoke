"""Fault-injection harness for installable product-boundary tests."""

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
            payload = json.loads(line[len(BOUNDARY_MARKER) :])
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
    assert run.boundary["yoke_config"] == run.boundary["yoke_machine_config_file"]


def _repo_pythonpath(run: ProductCliRun) -> list[str]:
    paths = []
    for raw in run.boundary["pythonpath"]:
        resolved = Path(str(raw)).resolve()
        if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
            paths.append(str(resolved))
    return paths


__all__ = [
    "REPO_ROOT",
    "ProductCliRun",
    "_assert_clean_client_boundary",
    "_run_product_cli",
]
