"""Product-wheel smoke for project onboarding dry-run.

The engine wheel (yoke-core) installs alongside the client; the dry-run stays
a pure product-client flow with the engine present but inert, and mutates
nothing.
"""

from __future__ import annotations

from tests.import_graph.onboard_wheel_smoke_support import _product_env as base_product_env

from yoke_contracts.venv_layout import venv_console_script, venv_python as venv_interpreter

import json
import os
import subprocess
from pathlib import Path




def smoke(
    tmp_path: Path,
    product_wheelhouse: Path,
    product_venv: Path,
) -> None:
    venv_dir = product_venv
    venv_python = venv_interpreter(venv_dir)
    yoke = venv_console_script(venv_dir, "yoke")
    assert yoke.is_file()

    checkout = tmp_path / "external-project"
    checkout.mkdir()
    _run(["git", "init"], cwd=checkout)
    (checkout / "README.md").write_text("# external\n", encoding="utf-8")
    before_checkout = _tree_snapshot(checkout)

    machine_home = tmp_path / "home" / ".yoke"
    machine_home.mkdir(parents=True)
    config = machine_home / "config.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "active_env": "prod",
                "connections": {
                    "prod": {
                        "transport": "https",
                        "api_url": "https://api.example.invalid",
                        "credential_source": {
                            "kind": "token_file",
                            "path": str(machine_home / "secrets" / "prod.token"),
                        },
                    },
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    before_config = config.read_text(encoding="utf-8")
    env = _product_env(machine_home, venv_dir)

    # The orchestration helper must also import first in a fresh interpreter;
    # source-suite import order can otherwise hide package-internal cycles.
    _run(
        [
            str(venv_python),
            "-c",
            "import importlib; "
            "importlib.import_module('yoke_cli.config.project_onboard_existing')",
        ],
        cwd=checkout,
        env=env,
    )

    # Engine present: the wheel channel ships yoke-core to every machine.
    _run(
        [
            str(venv_python),
            "-c",
            "import importlib.util; "
            "assert importlib.util.find_spec('yoke_core') is not None",
        ],
        cwd=checkout,
        env=env,
    )

    result = _run(
        [
            str(yoke),
            "onboard",
            "project",
            str(checkout),
            "--slug",
            "external",
            "--name",
            "External",
            "--github-repo",
            "owner/external",
            "--default-branch",
            "main",
            "--public-item-prefix",
            "EXT",
            "--config",
            str(config),
            "--dry-run",
            "--json",
        ],
        cwd=checkout,
        env=env,
    )
    payload = json.loads(result.stdout)
    assert payload["operation"] == "onboard.project"
    assert payload["applied"] is False
    assert payload["checkout"] == {
        "path": str(checkout.resolve()),
        "mode": "existing-local",
    }
    assert payload["plan"] == [
        "project.upsert",
        "project.capabilities.configure",
        "project.checkout.register",
        "project.install",
    ]
    assert _tree_snapshot(checkout) == before_checkout
    assert config.read_text(encoding="utf-8") == before_config
    assert not (checkout / ".yoke/install-manifest.json").exists()


def _product_env(machine_home: Path, venv_dir: Path) -> dict[str, str]:
    env = base_product_env(machine_home, venv_dir)
    return env


def _tree_snapshot(root: Path) -> list[tuple[str, str, str]]:
    snapshot: list[tuple[str, str, str]] = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_dir():
            snapshot.append(("dir", rel, ""))
        else:
            snapshot.append(("file", rel, path.read_text("utf-8")))
    return snapshot


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    run_env = dict(env) if env is not None else os.environ.copy()
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
    if check:
        assert result.returncode == 0, (
            f"command failed with {result.returncode}: {result.args!r}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result
