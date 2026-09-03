"""Pin the TypeScript contract's checked-in runtime and declaration emits."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from yoke_core.domain.yaml_helper import load_document


_REPO_ROOT = Path(__file__).resolve().parents[2]
_UI_RELATIVE = Path("packages/yoke-core/src/yoke_core/ui")
_UI_ROOT = _REPO_ROOT / _UI_RELATIVE
_TYPESCRIPT_COMPILER = _UI_ROOT / "node_modules" / "typescript" / "bin" / "tsc"
_TSC_INSTALL_COMMAND = f"npm ci --prefix {_UI_RELATIVE.as_posix()}"
_TSC_TIMEOUT_SECONDS = 30


def test_yoke_ci_preinstalls_typescript_for_contract_check() -> None:
    workflow = load_document(_REPO_ROOT / ".github" / "workflows" / "yoke-ci.yml")
    steps = workflow["jobs"]["test_shard"]["steps"]
    step_names = [step["name"] for step in steps]
    setup_index = step_names.index("Set up Node.js")
    install_index = step_names.index("Install TypeScript compiler")

    assert setup_index < install_index
    assert steps[setup_index]["with"] == {
        "node-version": "22",
        "cache": "npm",
        "cache-dependency-path": f"{_UI_RELATIVE.as_posix()}/package-lock.json",
    }
    assert steps[install_index]["run"] == _TSC_INSTALL_COMMAND


def test_universe_app_contract_tsc_outputs_are_current(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip(
            "Node.js is unavailable for the TypeScript contract check. CI provisions "
            f"it; locally, install Node.js and run `{_TSC_INSTALL_COMMAND}`."
        )
    assert _TYPESCRIPT_COMPILER.is_file(), (
        "The pinned TypeScript compiler is not installed. Run "
        f"`{_TSC_INSTALL_COMMAND}` from the repository root."
    )

    contracts = _UI_ROOT / "contracts"
    try:
        completed = subprocess.run(
            [
                node,
                str(_TYPESCRIPT_COMPILER),
                "-p",
                str(contracts / "tsconfig.json"),
                "--emitDeclarationOnly",
                "false",
                "--outDir",
                str(tmp_path),
                "--pretty",
                "false",
            ],
            cwd=_REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=_TSC_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as expired:
        raise AssertionError(
            "The pre-installed TypeScript compiler exceeded the "
            f"{_TSC_TIMEOUT_SECONDS}s compile-only timeout, so the contract was never "
            "compared. Inspect machine load and rerun this test; no package download "
            "is part of this command."
        ) from expired
    assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"
    assert (tmp_path / "universe-app.d.ts").read_bytes() == (
        contracts / "universe-app.d.ts"
    ).read_bytes()
    assert (tmp_path / "universe-app.js").read_bytes() == (
        _UI_ROOT / "static" / "contract-version.js"
    ).read_bytes()
