"""Wheels-only engine completeness smoke: boot and serve with no checkout.

Installs ``yoke-core`` — resolving ONLY its declared wheel metadata
dependencies — into an isolated venv from the locally built wheelhouse,
then asserts in a subprocess whose ``sys.path`` never sees the repo tree:

1. ``import yoke_core.domain`` succeeds. The universe boot path
   (``universe_is_born`` → frontier → session canonicalization) imports
   this package, so an undeclared package dependency (e.g. a wheel-shipped
   module importing a package absent from ``pyproject.toml``) fails here.
2. ``import yoke_core.api.main`` succeeds. ``main`` builds the FastAPI app
   at import (``app = create_app()``), which imports every registered
   route module — so a packaged module reaching for the repo-tree
   ``runtime.*`` package (which no wheel ships) fails here and the API
   would be unservable on a product machine.

Serving ``/v1/health`` against a live DB is deliberately out of scope: app
construction happens at import and DB initialization is deferred to the
ASGI lifespan, so the import assertions above already prove servability
without the cost/flake of a scratch Postgres cluster.

The venv is built without ``--system-site-packages`` and the subprocess
runs with a minimal environment (no ``PYTHONPATH``) from a temp cwd: this
is the install shape of a product machine that received wheels from the
package index and never cloned the repository.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from yoke_core.tools.build_release import create_seeded_pip_venv


BASE_PATH = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def test_engine_wheel_boots_and_serves_standalone(
    tmp_path: Path,
    product_wheelhouse: Path,
) -> None:
    venv_dir = tmp_path / "venv"
    create_seeded_pip_venv(venv_dir)
    venv_python = venv_dir / "bin" / "python"
    _run(
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--find-links",
            str(product_wheelhouse),
            "yoke-core",
        ],
        cwd=tmp_path,
        timeout=300,
    )

    home = tmp_path / "home"
    home.mkdir()
    env = {
        "HOME": str(home),
        "PATH": f"{venv_dir / 'bin'}:{BASE_PATH}",
        "PYTHONNOUSERSITE": "1",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
    }

    isolation_check = (
        "import importlib.util\n"
        "assert importlib.util.find_spec('runtime') is None, "
        "'repo tree leaked into the wheels-only venv'\n"
    )

    # Boot path: the domain package must resolve every import from
    # wheel-shipped homes declared in yoke-core's metadata.
    _run(
        [str(venv_python), "-c", isolation_check + "import yoke_core.domain\nprint('ok')"],
        cwd=tmp_path,
        env=env,
        timeout=120,
    )

    # Serve path: building the app imports every registered route module.
    _run(
        [str(venv_python), "-c", isolation_check + "import yoke_core.api.main\nprint('ok')"],
        cwd=tmp_path,
        env=env,
        timeout=120,
    )


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    run_env = dict(env) if env is not None else os.environ.copy()
    if env is None:
        run_env.pop("PYTHONPATH", None)
    result = subprocess.run(
        command,
        cwd=cwd,
        env=run_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    assert result.returncode == 0, (
        f"command failed with {result.returncode}: {result.args!r}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    return result
