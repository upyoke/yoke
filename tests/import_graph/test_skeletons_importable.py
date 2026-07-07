"""Package-split import-boundary checks for client packages."""

import ast
import importlib
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from runtime.api.product_boundary_isolation import write_sitecustomize

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.9/3.10 test hosts.
    import tomli as tomllib  # type: ignore[no-redef]


REPO_ROOT = Path(__file__).resolve().parents[2]

PACKAGE_ROOTS = {
    "yoke_contracts": REPO_ROOT / "packages" / "yoke-contracts",
    "yoke_cli": REPO_ROOT / "packages" / "yoke-cli",
    "yoke_harness": REPO_ROOT / "packages" / "yoke-harness",
}

FORBIDDEN_IMPORTS = {
    "yoke_contracts": (
        "yoke_core",
        "yoke_cli",
        "yoke_harness",
        "runtime.api",
        "runtime.harness",
        "psycopg",
    ),
    "yoke_cli": ("yoke_core", "runtime.api", "runtime.harness", "psycopg"),
    "yoke_harness": (
        "yoke_core",
        "runtime.api",
        "runtime.harness",
        "psycopg",
    ),
}

FORBIDDEN_DEPENDENCIES = {
    "yoke-contracts": ("yoke-core", "yoke-cli", "yoke-harness", "psycopg"),
    "yoke-cli": ("yoke-core", "psycopg"),
    "yoke-harness": ("yoke-core", "psycopg"),
}

FORBIDDEN_SCRIPT_TARGETS = ("runtime.", "yoke_core.")

PRODUCT_SMOKE_MODULES = {
    "yoke_contracts": (
        "yoke_contracts",
        "yoke_contracts.api.function_call",
        "yoke_contracts.machine_config.schema",
        "yoke_contracts.project_contract.scaffolds",
        # The board render ships in contracts so a managed project can render
        # its board without loading engine code: render_board_from_payload +
        # ReplayBoardDB must import with no yoke_core / psycopg on the path.
        "yoke_contracts.board.renderer",
        "yoke_contracts.board.data",
    ),
    "yoke_cli": (
        "yoke_cli",
        "yoke_cli.config.machine_config",
        "yoke_cli.transport.dispatcher",
        "yoke_cli.transport.https",
    ),
    "yoke_harness": ("yoke_harness",),
}


def test_client_package_roots_import():
    for name in PACKAGE_ROOTS:
        mod = importlib.import_module(name)
        assert mod.__name__ == name


def test_client_packages_do_not_import_core_runtime_or_db_driver():
    violations = []
    for package_name, package_root in PACKAGE_ROOTS.items():
        for path in sorted((package_root / "src").rglob("*.py")):
            for imported in _imported_modules(path):
                if _matches_any(imported, FORBIDDEN_IMPORTS[package_name]):
                    violations.append(
                        f"{path.relative_to(REPO_ROOT)} imports {imported!r}"
                    )

    assert violations == []


def test_client_package_metadata_does_not_depend_on_core_or_db_driver():
    violations = []
    for package_root in PACKAGE_ROOTS.values():
        pyproject = package_root / "pyproject.toml"
        data = tomllib.loads(pyproject.read_text())
        project = data["project"]
        package_name = project["name"]
        for dependency in _project_dependencies(project):
            dep_name = _dependency_name(dependency)
            if _matches_any(dep_name, FORBIDDEN_DEPENDENCIES[package_name]):
                rel_path = pyproject.relative_to(REPO_ROOT)
                violations.append(f"{rel_path} depends on {dependency!r}")
        for script_name, target in project.get("scripts", {}).items():
            if target.startswith(FORBIDDEN_SCRIPT_TARGETS):
                violations.append(
                    f"{pyproject.relative_to(REPO_ROOT)} script "
                    f"{script_name!r} points at {target!r}"
                )

    assert violations == []


@pytest.mark.parametrize("package_name", sorted(PACKAGE_ROOTS))
def test_product_src_only_imports_do_not_load_core_runtime_or_db_driver(
    package_name, tmp_path
):
    modules = PRODUCT_SMOKE_MODULES[package_name]
    forbidden = FORBIDDEN_IMPORTS[package_name]
    code = f"""
import importlib
import importlib.abc
import json
import os
import sys
from pathlib import Path

repo_root = Path(os.environ["YOKE_TEST_REPO_ROOT"]).resolve()
allowed_src = {{
    Path(p).resolve()
    for p in os.environ["PYTHONPATH"].split(os.pathsep)
    if p
}}

unexpected_repo_paths = []
for raw in sys.path:
    if not raw:
        continue
    resolved = Path(raw).resolve()
    under_repo = resolved == repo_root or repo_root in resolved.parents
    # The dependency site-packages is under the repo root on CI (the .venv lives
    # in the checkout), and the isolation sitecustomize re-adds it so third-party
    # deps (pydantic, etc.) import. It is NOT a repo *source* path, and the
    # ForbiddenImportFinder still blocks any forbidden import, so exempt it.
    if under_repo and resolved not in allowed_src and resolved.name != "site-packages":
        unexpected_repo_paths.append(str(resolved))
if unexpected_repo_paths:
    raise AssertionError(
        "subprocess import smoke must not see repo-root paths: "
        + ", ".join(unexpected_repo_paths)
    )

forbidden = tuple({forbidden!r})

def matches_forbidden(name):
    return any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)

class ForbiddenImportFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if matches_forbidden(fullname):
            raise AssertionError(f"attempted forbidden import {{fullname!r}}")
        return None

sys.meta_path.insert(0, ForbiddenImportFinder())
for module_name in {modules!r}:
    importlib.import_module(module_name)

leaked = sorted(name for name in sys.modules if matches_forbidden(name))
if leaked:
    raise AssertionError("forbidden modules loaded: " + ", ".join(leaked))
print(json.dumps({{"imported": {modules!r}}}, sort_keys=True))
"""
    _run_product_python(code, tmp_path=tmp_path)


def test_product_local_postgres_with_unimportable_engine_returns_loud_error(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "dev",
                "connections": {
                    "dev": {
                        "transport": "local-postgres",
                        "credential_source": {
                            "kind": "env",
                            "name": "YOKE_TEST_DSN",
                        },
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    code = """
import importlib.abc
import json
import sys

from yoke_cli.transport.dispatcher import call_dispatcher
from yoke_contracts.api.function_call import TargetRef

class ProductInstallCoreBlocker(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "yoke_core" or fullname.startswith("yoke_core."):
            raise ModuleNotFoundError(
                "No module named 'yoke_core'", name=fullname
            )
        if (
            fullname == "runtime.api"
            or fullname.startswith("runtime.api.")
            or fullname == "runtime.harness"
            or fullname.startswith("runtime.harness.")
            or fullname == "psycopg"
            or fullname.startswith("psycopg.")
        ):
            raise AssertionError(f"product local-postgres path imported {fullname!r}")
        return None

sys.meta_path.insert(0, ProductInstallCoreBlocker())
response = call_dispatcher(
    function_id="status.run",
    target=TargetRef(kind="global"),
    payload={},
)
assert response.success is False
assert response.error is not None
assert response.error.code == "local_postgres_core_unavailable"
assert (
    "dispatches in-process through the yoke-core engine"
    in response.error.message
)
assert "not importable" in response.error.message
hint = response.error.recovery_hint or ""
assert "dispatches in-process by design" in hint
assert "yoke env use" in hint
print(json.dumps(response.model_dump(mode="json"), sort_keys=True))
"""
    _run_product_python(
        code,
        tmp_path=tmp_path,
        extra_env={
            "YOKE_MACHINE_CONFIG_FILE": str(config_path),
            "YOKE_ENV": "dev",
            "YOKE_TEST_DSN": "postgresql://unused.example/yoke",
        },
    )


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.append(node.module)
    return imported


def _matches_any(value: str, prefixes: tuple[str, ...]) -> bool:
    return any(
        value == prefix or value.startswith(f"{prefix}.") for prefix in prefixes
    )


def _project_dependencies(project: dict[str, object]) -> list[str]:
    dependencies = list(project.get("dependencies", []))
    optional = project.get("optional-dependencies", {})
    if isinstance(optional, dict):
        for group_dependencies in optional.values():
            dependencies.extend(group_dependencies)
    return dependencies


def _dependency_name(requirement: str) -> str:
    name = requirement.split("[", 1)[0]
    for separator in ("<", ">", "=", "!", "~", ";"):
        name = name.split(separator, 1)[0]
    return name.strip().lower().replace("_", "-")


def _run_product_python(
    code: str,
    *,
    tmp_path: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": os.pathsep.join(
                (
                    str(
                        write_sitecustomize(
                            tmp_path,
                            repo_root=REPO_ROOT,
                            allowed_repo_paths=(
                                package_root / "src"
                                for package_root in PACKAGE_ROOTS.values()
                            ),
                        )
                    ),
                    *(
                        str(package_root / "src")
                        for package_root in PACKAGE_ROOTS.values()
                    ),
                )
            ),
            "PYTHONNOUSERSITE": "1",
            "YOKE_TEST_REPO_ROOT": str(REPO_ROOT),
        }
    )
    env.pop("YOKE_MACHINE_CONFIG_FILE", None)
    env.pop("YOKE_ENV", None)
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, (
        f"product subprocess failed with {result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    return result
