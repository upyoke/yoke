"""Pin the TypeScript contract's checked-in runtime and declaration emits."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


_TYPESCRIPT_PACKAGE = "typescript@5.9.3"


def test_universe_app_contract_tsc_outputs_are_current(tmp_path: Path) -> None:
    npx = shutil.which("npx")
    if npx is None:
        pytest.skip("npx is unavailable for the TypeScript contract drift check")

    repo_root = Path(__file__).resolve().parents[2]
    ui_root = repo_root / "packages" / "yoke-core" / "src" / "yoke_core" / "ui"
    contracts = ui_root / "contracts"
    completed = subprocess.run(
        [
            npx,
            "--yes",
            "--package",
            _TYPESCRIPT_PACKAGE,
            "tsc",
            "-p",
            str(contracts / "tsconfig.json"),
            "--emitDeclarationOnly",
            "false",
            "--outDir",
            str(tmp_path),
            "--pretty",
            "false",
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, (
        f"{completed.stdout}\n{completed.stderr}"
    )
    assert (tmp_path / "universe-app.d.ts").read_bytes() == (
        contracts / "universe-app.d.ts"
    ).read_bytes()
    assert (tmp_path / "universe-app.js").read_bytes() == (
        ui_root / "static" / "contract-version.js"
    ).read_bytes()
