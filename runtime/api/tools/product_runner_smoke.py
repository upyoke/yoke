"""Manual disposable-runner product smoke; no harness login or hosted universe."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

try:
    from .product_runner_hooks import replay_hooks
except ImportError:
    from product_runner_hooks import replay_hooks


class SmokeFailure(RuntimeError):
    """A smoke assertion failed; its named capture carries recovery evidence."""


class Commands:
    def __init__(self, output: Path, env: dict[str, str]):
        self.output, self.env = output, env
        self.sequence = 0
        self.step = "runner-identity"
        self.capture = output / "report.json"

    def failure(self, reason, detail):
        return SmokeFailure(
            f"{reason}: step={self.step}: {detail}; inspect {self.capture}, "
            "correct the named step and rerun the plan"
        )

    def run(self, name, command, *, cwd, stdin=None, accepted=(0,), shell=False):
        self.sequence += 1
        capture = self.output / f"{self.sequence:02d}-{name}.txt"
        self.step, self.capture = name, capture
        print(f"product-smoke step={name} capture={capture}", flush=True)
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                env=self.env,
                input=stdin,
                text=True,
                capture_output=True,
                timeout=900,
                shell=shell,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            capture.write_text(str(exc), encoding="utf-8")
            reason = (
                "command_timeout"
                if isinstance(exc, subprocess.TimeoutExpired)
                else "command_start_failed"
            )
            raise self.failure(reason, str(exc)) from exc
        capture.write_text(
            f"command={command!r}\nexit_code={result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
            encoding="utf-8",
        )
        if result.returncode not in accepted:
            raise self.failure("command_failed", f"exit={result.returncode}")
        return result

    def document(self, name, command, *, cwd):
        result = self.run(name, command, cwd=cwd)
        try:
            payload = json.loads(result.stdout)
            if not isinstance(payload, dict):
                raise ValueError("expected a JSON object")
        except ValueError as exc:
            raise self.failure("command_json_invalid", str(exc)) from exc
        if payload.get("success") is False:
            raise self.failure("command_refused", payload.get("error"))
        return payload.get("result", payload)


def isolated_environment(scratch: Path, venv: Path) -> dict[str, str]:
    """Explicit child environment: no tokens, DSNs, session identity, or API URLs."""
    home = scratch / "home"
    home.mkdir()
    return {
        "HOME": str(home),
        "YOKE_MACHINE_HOME": str(home / ".yoke"),
        "XDG_BIN_HOME": str(venv / "bin"),
        "PATH": f"{venv / 'bin'}:{Path(shutil.which('uv') or '').parent}:{os.defpath}:/usr/local/bin:/opt/homebrew/bin",
        "SHELL": "/bin/bash",
        "LANG": "en_US.UTF-8",
        "PYTHONNOUSERSITE": "1",
        "YOKE_PYTEST_LOCAL": "1",
        "GIT_CONFIG_GLOBAL": str(home / ".gitconfig"),
        "GIT_CONFIG_NOSYSTEM": "1",
    }


def observed_runner() -> dict[str, str]:
    if sys.platform == "darwin":
        os_name = f"macOS {platform.mac_ver()[0].split('.')[0]}"
    elif sys.platform == "linux":
        release = platform.freedesktop_os_release()
        os_name = f"{release['NAME']} {release['VERSION_ID']}"
    else:
        os_name = platform.system()
    return {"os": os_name, "architecture": platform.machine()}


def smoke(root: Path, output: Path) -> None:
    report = {"ok": False}
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
            venv, wheels, project = (
                scratch / part for part in ("venv", "wheels", "project")
            )
            commands = Commands(output, isolated_environment(scratch, venv))
            commands.run(
                "build-wheels",
                ["uv", "build", "--all-packages", "--wheel", "--out-dir", str(wheels)],
                cwd=root,
            )
            commands.run(
                "create-venv",
                ["uv", "venv", "--python", sys.executable, str(venv)],
                cwd=scratch,
            )
            built = sorted(str(path) for path in wheels.glob("*.whl"))
            if not built:
                raise SmokeFailure(
                    "wheel_build_empty: no wheels; inspect build-wheels capture"
                )
            commands.run(
                "install-product",
                ["uv", "pip", "install", "--python", str(venv / "bin/python3"), *built],
                cwd=scratch,
            )
            project.mkdir()
            commands.run(
                "git-identity-name",
                ["git", "config", "--global", "user.name", "Yoke Smoke"],
                cwd=project,
            )
            commands.run(
                "git-identity-email",
                ["git", "config", "--global", "user.email", "smoke@yoke.local"],
                cwd=project,
            )
            commands.run(
                "git-init", ["git", "init", "--initial-branch=main"], cwd=project
            )
            (project / "README.md").write_text(
                "# Disposable smoke project\n", encoding="utf-8"
            )
            commands.run("git-add", ["git", "add", "README.md"], cwd=project)
            commands.run(
                "git-commit",
                ["git", "commit", "-m", "Initialize disposable project"],
                cwd=project,
            )
            yoke = str(venv / "bin/yoke")
            try:
                onboard = commands.document(
                    "onboard",
                    [
                        yoke,
                        "onboard",
                        "--local",
                        "--non-interactive",
                        "--yes",
                        "--json",
                        "--machine-github",
                        "disabled",
                        "--github-adoption",
                        "disabled",
                        "--project-mode",
                        "local-checkout",
                        "--checkout",
                        str(project),
                        "--project-slug",
                        "smoke",
                        "--project-name",
                        "Smoke",
                        "--default-branch",
                        "main",
                        "--public-item-prefix",
                        "SMK",
                    ],
                    cwd=project,
                )
                if not onboard.get("applied") or not onboard.get(
                    "local_universe", {}
                ).get("born"):
                    raise SmokeFailure(
                        "onboard_not_born: fresh local onboarding did not apply and birth the universe; inspect onboard capture"
                    )
                # The destructive guard refuses threatened state. Give the
                # denied clean probe an untracked file; never execute it.
                (project / "untracked-probe.txt").write_text(
                    "Preserve this probe.\n", encoding="utf-8"
                )
                report["hooks"] = replay_hooks(root, project, commands, yoke)
                dev = commands.document(
                    "dev-setup",
                    [
                        yoke,
                        "dev",
                        "setup",
                        str(root),
                        "--editable-install",
                        "--yes",
                        "--json",
                    ],
                    cwd=root,
                )
                if not dev.get("applied"):
                    raise SmokeFailure(
                        "dev_setup_not_applied: inspect dev-setup capture and rerun"
                    )
                if not dev.get("editable_install", {}).get("ok"):
                    raise SmokeFailure(
                        "editable_install_failed: inspect dev-setup capture and repair its named dependency"
                    )
                commands.run(
                    "install-test-dependencies",
                    ["uv", "sync", "--all-packages", "--all-groups", "--locked"],
                    cwd=root,
                )
                commands.run(
                    "pytest-subset",
                    [
                        yoke,
                        "watch",
                        "pytest",
                        "--local",
                        "--",
                        "runtime/harness/test_hook_runner_decision_render.py",
                        "tests/import_graph/test_yoke_cli_dev_setup_contract.py",
                        "-q",
                    ],
                    cwd=root,
                )
                report["ok"] = True
            except Exception as exc:
                failure = (
                    exc
                    if isinstance(exc, SmokeFailure) and "step=" in str(exc)
                    else commands.failure("smoke_assertion_failed", str(exc))
                )
                try:
                    commands.run(
                        "failure-events",
                        [yoke, "events", "query", "--limit", "50", "--json"],
                        cwd=project,
                    )
                except SmokeFailure:
                    pass  # The diagnostic capture cannot replace the primary failure.
                raise failure from exc
            finally:
                primary_failure = sys.exc_info()[0] is not None
                try:
                    if sys.platform == "darwin":
                        commands.run(
                            "uninstall-local-relay",
                            [yoke, "relay", "uninstall", "--json"],
                            cwd=project,
                        )
                    commands.run(
                        "stop-local-postgres",
                        [yoke, "postgres", "stop", "--json"],
                        cwd=project,
                    )
                except SmokeFailure:
                    if not primary_failure:
                        raise
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
    print(f"product-smoke passed: {output / 'report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
