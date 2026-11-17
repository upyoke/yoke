"""Disposable-runner product smoke; no harness login or hosted universe.

Every runner runs every stage in order (see :mod:`product_runner_stages`).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import stat
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
# A real Windows session always carries these; PowerShell and COM expect them.
# The PowerShell module path and analysis cache keep the hooks' and relay's
# cmdlet lookups from rebuilding a cache over every module on the runner image
# (20-50 seconds per process); a user's own profile keeps that cache warm.
WINDOWS_SYSTEM_VARIABLES = (
    "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT",
    "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "PROGRAMDATA", "ALLUSERSPROFILE",
    "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)", "COMMONPROGRAMW6432", "PUBLIC",
    "COMPUTERNAME", "USERNAME", "USERDOMAIN", "OS", "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER", "PROCESSOR_LEVEL", "PROCESSOR_REVISION",
    "PSMODULEPATH", "PSMODULEANALYSISCACHEPATH",
)  # fmt: skip
SCRATCH_PREFIX = "yps-"


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
        # A real profile's temp folder is short; one nested under this scratch
        # home would push Postgres socket fallbacks past the Unix-socket limit.
        temp = scratch / "tmp"
        temp.mkdir()
        (home / "AppData" / "Local").mkdir(parents=True)
        env |= {name: os.environ[name] for name in WINDOWS_SYSTEM_VARIABLES if name in os.environ}
        env |= {
            "USERPROFILE": str(home),
            "APPDATA": str(home / "AppData" / "Roaming"),
            "LOCALAPPDATA": str(home / "AppData" / "Local"),
            "TEMP": str(temp),
            "TMP": str(temp),
        }
        system = Path(env.get("SYSTEMROOT", r"C:\Windows")) / "System32"
        # Rendered Windows hooks start powershell.exe, which lives outside System32 proper.
        powershell = system / "WindowsPowerShell" / "v1.0"
        env["PATH"] = os.pathsep.join(str(path) for path in (*tools, system, powershell))
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


def cleanup(run: SmokeRun, *, primary_failure: bool) -> None:
    """Stop what onboarding started; a cleanup failure never hides the primary one.

    Each step runs even when an earlier one fails: a relay that cannot be
    removed must not leave Postgres holding the scratch folder open. The hook
    replay started the resident hook evaluator, so it stops first.
    """
    first = None
    for name, argv in (
        ("stop-hook-resident", [run.yoke, "hook", "resident", "stop"]),
        ("uninstall-local-relay", [run.yoke, "relay", "uninstall", "--json"]),
        ("stop-local-postgres", [run.yoke, "local-postgres", "stop", "--json"]),
    ):
        try:
            run.commands.run(name, argv, cwd=run.project)
        except SmokeFailure as exc:
            first = first or exc
    if first and not primary_failure:
        raise first


def remove_scratch(scratch: Path, report: dict, *, primary_failure: bool) -> None:
    """Delete the scratch folder; a leftover process never hides the primary failure."""
    def writable(function, path, _error):
        os.chmod(path, stat.S_IWRITE)  # Windows refuses to delete Git's read-only objects.
        function(path)

    handler = {"onexc" if sys.version_info >= (3, 12) else "onerror": writable}
    try:
        shutil.rmtree(scratch, **handler)
    except OSError as exc:
        detail = (
            f"scratch_cleanup_failed: {exc}; a process the smoke started still holds "
            "a scratch file. Inspect the stop-hook-resident, uninstall-local-relay and "
            "stop-local-postgres captures"
        )
        if not primary_failure:
            raise SmokeFailure(detail) from exc
        report["scratch_cleanup_failure"] = detail


def run_stages(run: SmokeRun) -> None:
    failed = True
    try:
        for name, stage in STAGES:
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


def smoke(root: Path, output: Path) -> None:
    report = {"ok": False, "stages": list(STAGE_NAMES)}
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
        # Keep the scratch prefix short: the local universe's Postgres socket
        # lives under the scratch HOME, and Windows' temp folder is already deep.
        scratch = Path(tempfile.mkdtemp(prefix=SCRATCH_PREFIX)).resolve()
        try:
            commands = Commands(output, isolated_environment(scratch, scratch / "venv"))
            run_stages(SmokeRun(root, scratch, commands, report))
        finally:
            remove_scratch(scratch, report, primary_failure=sys.exc_info()[0] is not None)
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
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[3]
    try:
        smoke(root, output)
    except SmokeFailure as exc:
        print(f"product-smoke failed: {exc}", file=sys.stderr)
        return 1
    print(f"product-smoke passed {', '.join(STAGE_NAMES)}: {output / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
