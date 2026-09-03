"""Pin the TypeScript contract's checked-in runtime and declaration emits."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


_TYPESCRIPT_PACKAGE = "typescript@5.9.3"
#: The first run on a cold machine downloads the compiler before it compiles
#: anything, and this test shares its shard with whatever else lands there, so
#: the budget has to cover a registry fetch under load rather than a warm
#: compile alone. Too tight a bound reads as contract drift on a green tree.
_TSC_TIMEOUT_SECONDS = 300


def test_universe_app_contract_tsc_outputs_are_current(tmp_path: Path) -> None:
    npx = shutil.which("npx")
    if npx is None:
        pytest.skip("npx is unavailable for the TypeScript contract drift check")

    repo_root = Path(__file__).resolve().parents[2]
    ui_root = repo_root / "packages" / "yoke-core" / "src" / "yoke_core" / "ui"
    contracts = ui_root / "contracts"
    try:
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
            timeout=_TSC_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as expired:
        # Say which of the two things ran out of time. A bare traceback here
        # reads as a broken contract, and the tree it was checking is fine.
        raise AssertionError(
            f"{_TYPESCRIPT_PACKAGE} did not finish within "
            f"{_TSC_TIMEOUT_SECONDS}s, so the contract was never compared. "
            "This is the compiler fetch or the machine, not contract drift; "
            "re-run, and raise _TSC_TIMEOUT_SECONDS if it keeps recurring."
        ) from expired
    assert completed.returncode == 0, f"{completed.stdout}\n{completed.stderr}"
    assert (tmp_path / "universe-app.d.ts").read_bytes() == (
        contracts / "universe-app.d.ts"
    ).read_bytes()
    assert (tmp_path / "universe-app.js").read_bytes() == (
        ui_root / "static" / "contract-version.js"
    ).read_bytes()
