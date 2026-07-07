"""Core flow for the product-wheel no-checkout CLI smoke.

Proves the machine-installed ``yoke`` CLI works from a directory with
no Yoke checkout: builds the worktree wheel into a fresh venv, then
drives the typed failure modes (missing config, missing credential,
unreachable relay, unknown env) plus browser-substrate and project-dir
hygiene through :mod:`product_cli_no_checkout_smoke_steps`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from yoke_contracts.api_urls import HOSTED_STAGE_URL

from yoke_core.tools.product_cli_no_checkout_smoke_steps import (
    STATUS_FAIL,
    STEP_WHEEL_INSTALL,
    SmokeContext,
    StepRunner,
    dir_entries,
    execute_steps,
    step_entry,
)
from yoke_core.tools.checkout_clean_room_smoke_helpers import (
    BASE_PATH,
    CommandResult,
    SmokeError,
    base_env,
    tail,
)

DEFAULT_API_URL = HOSTED_STAGE_URL
SMOKE_SESSION_ID = "product-cli-no-checkout-smoke"
TOKEN_FILE_NAME = "smoke.token"


def run_smoke(
    *,
    source_root: Path,
    api_url: str,
    online: bool,
    python: Path,
    work_dir: Path | None,
    keep_work_dir: bool,
) -> dict[str, Any]:
    source_root = source_root.resolve()
    if not (source_root / "pyproject.toml").is_file():
        raise SmokeError(f"source root has no pyproject.toml: {source_root}")

    root = work_dir or Path(tempfile.mkdtemp(prefix="yoke-product-cli-smoke-"))
    root.mkdir(parents=True, exist_ok=True)
    home = root / "home"
    machine_home = home / ".yoke"
    project_dir = root / "project"
    venv_dir = root / "venv"
    wheel_dir = root / "wheels"
    commands: list[CommandResult] = []

    try:
        home.mkdir(parents=True, exist_ok=True)
        project_dir.mkdir(parents=True, exist_ok=True)
        machine_home.mkdir(parents=True, exist_ok=True)
        provision_run = subprocess_runner(
            cwd=source_root, env=base_env(home), commands=commands,
        )
        provision_step = provision(
            provision_run,
            source_root=source_root,
            python=python,
            venv_dir=venv_dir,
            wheel_dir=wheel_dir,
        )
        steps = [provision_step]
        if provision_step["status"] != STATUS_FAIL:
            ctx = SmokeContext(
                api_url=api_url,
                online=online,
                project_dir=project_dir,
                machine_home=machine_home,
                yoke=venv_dir / "bin" / "yoke",
                venv_python=venv_dir / "bin" / "python",
                token_path=machine_home / TOKEN_FILE_NAME,
            )
            step_run = subprocess_runner(
                cwd=project_dir,
                env=no_checkout_env(
                    home=home,
                    machine_home=machine_home,
                    venv_bin=venv_dir / "bin",
                ),
                commands=commands,
            )
            steps.extend(execute_steps(ctx, step_run))
        return assemble_report(
            api_url=api_url,
            online=online,
            work_dir=root,
            work_dir_retained=keep_work_dir or work_dir is not None,
            project_dir=project_dir,
            machine_home=machine_home,
            yoke=venv_dir / "bin" / "yoke",
            steps=steps,
            commands=commands,
        )
    except OSError as exc:
        raise SmokeError(str(exc)) from exc
    finally:
        if not keep_work_dir and work_dir is None:
            shutil.rmtree(root, ignore_errors=True)


def provision(
    run: StepRunner,
    *,
    source_root: Path,
    python: Path,
    venv_dir: Path,
    wheel_dir: Path,
) -> dict[str, Any]:
    """Step 1: wheel-build product packages into a fresh venv."""
    failures: list[str] = []
    cli_wheel: Optional[Path] = None
    package_roots = _product_package_roots(source_root)
    build = run(
        [str(python), "-m", "pip", "wheel", "--wheel-dir", str(wheel_dir),
         *(str(path) for path in package_roots)],
        STEP_WHEEL_INSTALL,
    )
    if build.returncode != 0:
        failures.append(f"pip wheel failed with {build.returncode}: "
                        f"{tail(build.stderr)}")
    else:
        missing = _missing_product_wheels(wheel_dir)
        if missing:
            failures.append(
                "product wheel build missed: " + ", ".join(missing)
            )
        cli_wheel = _single_wheel(wheel_dir, "yoke_cli-*.whl")
    if not failures:
        venv_python = venv_dir / "bin" / "python"
        for label, command in (
            ("venv create", [str(python), "-m", "venv", str(venv_dir)]),
            ("pip upgrade",
             [str(venv_python), "-m", "pip", "install", "--upgrade", "pip"]),
            ("wheel install",
             [str(venv_python), "-m", "pip", "install", "--no-index",
              "--find-links", str(wheel_dir), "yoke-cli",
              "yoke-harness"]),
        ):
            result = run(command, STEP_WHEEL_INSTALL)
            if result.returncode != 0:
                failures.append(f"{label} failed with {result.returncode}: "
                                f"{tail(result.stderr)}")
                break
    yoke = venv_dir / "bin" / "yoke"
    if not failures and not yoke.is_file():
        failures.append(f"wheel install produced no yoke entrypoint: {yoke}")
    return step_entry(STEP_WHEEL_INSTALL, failures, {
        "wheel": (cli_wheel.name if cli_wheel else None),
        "product_wheels": _product_wheel_names(wheel_dir),
        "venv": str(venv_dir),
        "yoke_executable": str(yoke),
        "yoke_exists": yoke.is_file(),
    })


def _product_package_roots(source_root: Path) -> list[Path]:
    packages_dir = source_root / "packages"
    roots = [
        packages_dir / "yoke-contracts",
        packages_dir / "yoke-cli",
        packages_dir / "yoke-harness",
    ]
    missing = [str(path) for path in roots if not (path / "pyproject.toml").is_file()]
    if missing:
        raise SmokeError("missing product package pyproject(s): " + ", ".join(missing))
    return roots


def _single_wheel(wheel_dir: Path, pattern: str) -> Optional[Path]:
    wheels = sorted(wheel_dir.glob(pattern))
    return wheels[0] if len(wheels) == 1 else None


def _missing_product_wheels(wheel_dir: Path) -> list[str]:
    expected = {
        "yoke-cli": "yoke_cli-*.whl",
        "yoke-contracts": "yoke_contracts-*.whl",
        "yoke-harness": "yoke_harness-*.whl",
    }
    return [
        name for name, pattern in expected.items()
        if _single_wheel(wheel_dir, pattern) is None
    ]


def _product_wheel_names(wheel_dir: Path) -> list[str]:
    names: list[str] = []
    for pattern in (
        "yoke_cli-*.whl",
        "yoke_contracts-*.whl",
        "yoke_harness-*.whl",
    ):
        names.extend(wheel.name for wheel in sorted(wheel_dir.glob(pattern)))
    return sorted(names)


def no_checkout_env(
    *,
    home: Path,
    machine_home: Path,
    venv_bin: Path,
) -> dict[str, str]:
    """Isolated env for the no-checkout steps.

    Built from scratch (never copied from ``os.environ``) so ambient
    Yoke variables cannot leak in. Unlike the checkout clean-room env, this
    sets neither ``YOKE_ENV`` nor ``YOKE_MACHINE_CONFIG_FILE`` — env
    routing must come from the machine config's ``active_env`` (or a
    per-command ``--env``) and config resolution from
    ``YOKE_MACHINE_HOME``, because that is the no-checkout default
    path being proven.
    """
    return {
        "HOME": str(home),
        "PATH": f"{venv_bin}:{BASE_PATH}",
        "YOKE_MACHINE_HOME": str(machine_home),
        "YOKE_SESSION_ID": SMOKE_SESSION_ID,
        "PYTHONNOUSERSITE": "1",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
    }


def subprocess_runner(
    *,
    cwd: Path,
    env: dict[str, str],
    commands: list[CommandResult],
) -> StepRunner:
    """Real :data:`StepRunner`: capture everything, never raise on rc!=0."""

    def _run(command: list, step: str) -> CommandResult:
        completed = subprocess.run(
            [str(part) for part in command],
            cwd=str(cwd),
            env=dict(env),
            text=True,
            capture_output=True,
            check=False,
        )
        result = CommandResult(
            step=step,
            command=[str(part) for part in command],
            cwd=str(cwd),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        commands.append(result)
        return result

    return _run


def assemble_report(
    *,
    api_url: str,
    online: bool,
    work_dir: Path,
    work_dir_retained: bool,
    project_dir: Path,
    machine_home: Path,
    yoke: Path,
    steps: list[dict[str, Any]],
    commands: list[CommandResult],
) -> dict[str, Any]:
    """Project the step results into the printed report dict.

    ``ok`` is true only when no step failed; skipped steps do not fail
    the run. Machine-home writes are expected — they are listed, not
    asserted against.
    """
    return {
        "ok": not any(step["status"] == STATUS_FAIL for step in steps),
        "api_url": api_url,
        "online": online,
        "work_dir": str(work_dir),
        "work_dir_retained": work_dir_retained,
        "work_dir_note": (
            "retained for follow-up inspection"
            if work_dir_retained
            else "removed after report assembly; rerun with --keep-work-dir "
                 "for follow-up inspection"
        ),
        "project_dir": str(project_dir),
        "machine_home": str(machine_home),
        "yoke_executable": str(yoke),
        "steps": steps,
        "machine_home_entries": dir_entries(machine_home),
        "commands": [result.summary() for result in commands],
    }
