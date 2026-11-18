"""One isolated installed product environment shared across xdist workers."""

from yoke_contracts.venv_layout import venv_python

import os
from pathlib import Path
import subprocess

from filelock import FileLock
import pytest

from yoke_core.tools.build_release import create_seeded_pip_venv


@pytest.fixture(scope="session")
def product_venv(tmp_path_factory, pytestconfig, product_wheelhouse) -> Path:
    worker = getattr(pytestconfig, "workerinput", None)
    shared = (
        tmp_path_factory.getbasetemp().parent
        if worker
        else tmp_path_factory.getbasetemp()
    )
    directory = shared / "installed-product"
    sentinel = directory / ".installed"
    with FileLock(str(shared / "installed-product.lock")):
        if not sentinel.exists():
            create_seeded_pip_venv(directory)
            python = venv_python(directory)
            env = {
                key: value
                for key, value in os.environ.items()
                if key not in {"PYTHONPATH", "PYTHONHOME"}
            }
            command = [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-index",
                "--find-links",
                str(product_wheelhouse),
            ]
            subprocess.run(
                command + ["yoke-core"],
                env=env,
                cwd=shared,
                check=True,
                capture_output=True,
                text=True,
                timeout=300,
            )
            # Prove core's own dependency closure before installing the client.
            subprocess.run(
                [
                    str(python),
                    "-I",
                    "-c",
                    "import yoke_core.api.server_entrypoint; "
                    "import yoke_core.domain.schema_init; import yoke_core.api.main",
                ],
                env=env,
                cwd=shared,
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            subprocess.run(
                command + ["yoke-cli", "yoke-harness"],
                env=env,
                cwd=shared,
                check=True,
                capture_output=True,
                text=True,
                timeout=300,
            )
            sentinel.write_text("installed\n", encoding="utf-8")
    return directory
