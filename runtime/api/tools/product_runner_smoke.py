"""Disposable-runner product smoke; no harness login or hosted universe.

Stages run in order up to ``--through`` (see :mod:`product_runner_stages`).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import tempfile

try:
    from .product_runner_commands import Commands, SmokeFailure, venv_executable
    from .product_runner_linux_account import ACCOUNT_HOME, verified_account_environment
    from .product_runner_stages import STAGE_NAMES, STAGES, SmokeRun
except ImportError:
    from product_runner_commands import Commands, SmokeFailure, venv_executable
    from product_runner_linux_account import ACCOUNT_HOME, verified_account_environment
    from product_runner_stages import STAGE_NAMES, STAGES, SmokeRun

# Windows needs these to start Python, Git and uv at all; none carries authority.
WINDOWS = os.name == "nt"
WINDOWS_SYSTEM_VARIABLES = ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT")


def isolated_environment(scratch: Path, venv: Path) -> dict[str, str]:
    """Explicit child environment: no tokens, DSNs, session identity, or API URLs.

    Inside the Linux CI disposable account (see product_runner_linux_account),
    HOME is that account's real home and only its user-manager bus variables
    pass through, so the relay unit lands where its user manager looks.
    Everywhere else HOME is a fresh scratch folder.
    """
    service_env = {}
    if sys.platform == "linux" and os.environ.get(ACCOUNT_HOME):
        home, service_env = verified_account_environment()
    else:
        home = scratch / "home"
        home.mkdir()
    scripts = venv_executable(venv, "yoke").parent
    tools = [scripts, *(Path(found).parent for found in map(shutil.which, ("uv", "git")) if found)]
    env = {
        "HOME": str(home),
        "YOKE_MACHINE_HOME": str(home / ".yoke"),
        "XDG_BIN_HOME": str(scripts),
        "LANG": "en_US.UTF-8",
        "PYTHONNOUSERSITE": "1",
        "YOKE_PYTEST_LOCAL": "1",
        "GIT_CONFIG_GLOBAL": str(home / ".gitconfig"),
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    env.update(service_env)
    if WINDOWS:
        temp = home / "AppData" / "Local" / "Temp"
        temp.mkdir(parents=True)
        env |= {name: os.environ[name] for name in WINDOWS_SYSTEM_VARIABLES if name in os.environ}
        env |= {
            "USERPROFILE": str(home),
            "APPDATA": str(home / "AppData" / "Roaming"),
            "LOCALAPPDATA": str(home / "AppData" / "Local"),
            "TEMP": str(temp),
            "TMP": str(temp),
        }
        system = Path(env.get("SYSTEMROOT", r"C:\Windows")) / "System32"
        env["PATH"] = os.pathsep.join(str(path) for path in (*tools, system))
    else:
        defaults = (os.defpath, "/usr/local/bin", "/opt/homebrew/bin")
        env["PATH"] = os.pathsep.join([*(str(path) for path in tools), *defaults])
        env["SHELL"] = "/bin/bash"
    return env


def observed_runner() -> dict[str, str]:
    if sys.platform == "darwin":
        os_name = f"macOS {platform.mac_ver()[0].split('.')[0]}"
    elif sys.platform == "linux":
        release = platform.freedesktop_os_release()
        os_name = f"{release['NAME']} {release['VERSION_ID']}"
    elif sys.platform == "win32":
        os_name = f"Windows {platform.release()}"
    else:
        os_name = platform.system()
    architecture = platform.machine()
    architecture = {"aarch64": "arm64", "ARM64": "arm64", "AMD64": "x86_64"}.get(
        architecture, architecture
    )
    return {"os": os_name, "architecture": architecture}


def selected_stages(through: str):
    return STAGES[: STAGE_NAMES.index(through) + 1]


def cleanup(run: SmokeRun, *, primary_failure: bool) -> None:
    """Stop what onboarding started; a cleanup failure never hides the primary one."""
    try:
        if sys.platform in {"darwin", "linux"}:
            run.commands.run(
                "uninstall-local-relay",
                [run.yoke, "relay", "uninstall", "--json"],
                cwd=run.project,
            )
        run.commands.run(
            "stop-local-postgres",
            [run.yoke, "local-postgres", "stop", "--json"],
            cwd=run.project,
        )
    except SmokeFailure:
        if not primary_failure:
            raise


def run_stages(run: SmokeRun, through: str) -> None:
    failed = True
    try:
        for name, stage in selected_stages(through):
            run.report["stage"] = name
            stage(run)
        run.report["ok"] = True
        failed = False
    except Exception as exc:
        failure = (
            exc
            if isinstance(exc, SmokeFailure) and "step=" in str(exc)
            else run.commands.failure("smoke_assertion_failed", str(exc))
        )
        if run.onboarded:
            try:
                run.commands.run(
                    "failure-events",
                    [run.yoke, "events", "query", "--limit", "50", "--json"],
                    cwd=run.project,
                )
            except SmokeFailure:
                pass  # The diagnostic capture cannot replace the primary failure.
        raise failure from exc
    finally:
        if run.onboarded:
            cleanup(run, primary_failure=failed)


def smoke(root: Path, output: Path, through: str = STAGE_NAMES[-1]) -> None:
    report = {"ok": False, "through": through}
    report_path = output / "report.json"
    commands = None
    try:
        report["runner"] = observed_runner()
        expected = {
            "os": os.environ.get("SMOKE_EXPECTED_OS"),
            "architecture": os.environ.get("SMOKE_EXPECTED_ARCHITECTURE"),
        }
        if report["runner"] != expected:
            raise SmokeFailure(
                f"runner_identity_mismatch: expected {expected}, observed {report['runner']}; "
                "check the latest-label rollout and update the declared job identities before rerunning"
            )
        with tempfile.TemporaryDirectory(prefix="yoke-product-smoke-") as raw:
            scratch = Path(raw).resolve()
            commands = Commands(output, isolated_environment(scratch, scratch / "venv"))
            run_stages(SmokeRun(root, scratch, commands, report), through)
    except Exception as exc:
        report["ok"] = False
        failure = str(exc)
        if "inspect " not in failure or "step=" not in failure:
            failure = (
                str(commands.failure("smoke_failed", failure))
                if commands
                else (
                    f"smoke_failed: step=runner-identity: {failure}; inspect {report_path}, correct the named step and rerun the plan"
                )
            )
        report["failure"] = failure
        raise SmokeFailure(failure) from exc
    finally:
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--through",
        choices=STAGE_NAMES,
        default=STAGE_NAMES[-1],
        help="last stage to run; earlier stages always run first",
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[3]
    try:
        smoke(root, output, args.through)
    except SmokeFailure as exc:
        print(f"product-smoke failed: {exc}", file=sys.stderr)
        return 1
    print(f"product-smoke passed through {args.through}: {output / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
