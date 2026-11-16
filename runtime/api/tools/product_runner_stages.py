"""Ordered product-smoke stages; each lane appends the stage that proves its port.

A run executes the stages in order up to its cutoff (``--through``), so a
runner that cannot yet onboard still proves install and ``yoke status``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sys

try:
    from .product_runner_commands import Commands, SmokeFailure, venv_executable
    from .product_runner_hooks import replay_hooks
    from .product_runner_source_tests import run_source_tests
except ImportError:
    from product_runner_commands import Commands, SmokeFailure, venv_executable
    from product_runner_hooks import replay_hooks
    from product_runner_source_tests import run_source_tests


@dataclass
class SmokeRun:
    root: Path
    scratch: Path
    commands: Commands
    report: dict
    onboarded: bool = field(default=False)

    @property
    def venv(self) -> Path:
        return self.scratch / "venv"

    @property
    def project(self) -> Path:
        return self.scratch / "project"

    @property
    def home(self) -> Path:
        return Path(self.commands.env["HOME"])

    @property
    def yoke(self) -> str:
        return str(venv_executable(self.venv, "yoke"))


def install(run: SmokeRun) -> None:
    wheels = run.scratch / "wheels"
    run.commands.run(
        "build-wheels",
        ["uv", "build", "--all-packages", "--wheel", "--out-dir", str(wheels)],
        cwd=run.root,
    )
    run.commands.run(
        "create-venv",
        ["uv", "venv", "--python", sys.executable, str(run.venv)],
        cwd=run.scratch,
    )
    built = sorted(str(path) for path in wheels.glob("*.whl"))
    if not built:
        raise SmokeFailure("wheel_build_empty: no wheels; inspect build-wheels capture")
    python = str(venv_executable(run.venv, "python"))
    run.commands.run(
        "install-product",
        ["uv", "pip", "install", "--python", python, *built],
        cwd=run.scratch,
    )


def status(run: SmokeRun) -> None:
    """The installed CLI starts and names an empty machine as not set up."""
    empty = run.scratch / "empty-folder"
    empty.mkdir()
    version = run.commands.run("yoke-version", [run.yoke, "--version"], cwd=empty)
    if not version.stdout.strip():
        raise run.commands.failure("version_empty", "yoke --version printed nothing")
    run.commands.run("yoke-help", [run.yoke, "--help"], cwd=empty)
    result = run.commands.run(
        "yoke-status", [run.yoke, "status", "--json"], cwd=empty, accepted=(1,)
    )
    payload = run.commands.parse_json(result.stdout)
    payload = payload.get("result", payload)
    codes = {issue.get("code") for issue in payload.get("issues", [])}
    config = Path(payload.get("config_path") or "")
    if payload.get("ok") is not False or "config_missing" not in codes:
        raise run.commands.failure(
            "status_not_unset",
            f"expected ok=false naming config_missing, got ok={payload.get('ok')} codes={sorted(codes)}",
        )
    if not config.is_relative_to(run.home):
        raise run.commands.failure(
            "status_config_outside_home", f"config_path {config} is outside {run.home}"
        )
    run.report["status_issues"] = sorted(codes)


def onboard(run: SmokeRun) -> None:
    project, commands = run.project, run.commands
    project.mkdir()
    for name, argv in (
        ("git-identity-name", ["git", "config", "--global", "user.name", "Yoke Smoke"]),
        ("git-identity-email", ["git", "config", "--global", "user.email", "smoke@yoke.local"]),
        ("git-init", ["git", "init", "--initial-branch=main"]),
    ):
        commands.run(name, argv, cwd=project)
    (project / "README.md").write_text("# Disposable smoke project\n", encoding="utf-8")
    commands.run("git-add", ["git", "add", "README.md"], cwd=project)
    commands.run(
        "git-commit", ["git", "commit", "-m", "Initialize disposable project"], cwd=project
    )
    run.onboarded = True
    document = commands.document(
        "onboard",
        [
            run.yoke, "setup", "--local", "--non-interactive", "--yes", "--json",
            "--machine-github", "disabled", "--github-adoption", "disabled",
            "--project-mode", "local-checkout", "--checkout", str(project),
            "--project-slug", "smoke", "--project-name", "Smoke",
            "--default-branch", "main", "--public-item-prefix", "SMK",
        ],
        cwd=project,
    )  # fmt: skip
    if not document.get("applied") or not document.get("local_universe", {}).get("born"):
        raise SmokeFailure(
            "onboard_not_born: fresh local onboarding did not apply and birth the universe; inspect onboard capture"
        )
    if sys.platform.startswith("linux"):
        require_browser_installation(document, commands.capture)
        run.report["browser_install_authority"] = "passwordless sudo"


def hooks(run: SmokeRun) -> None:
    # The destructive guard refuses threatened state. Give the denied clean
    # probe an untracked file; never execute it.
    (run.project / "untracked-probe.txt").write_text(
        "Preserve this probe.\n", encoding="utf-8"
    )
    run.report["hooks"] = replay_hooks(run.root, run.project, run.commands, run.yoke)


def dev_setup(run: SmokeRun) -> None:
    dev = run.commands.document(
        "dev-setup",
        [run.yoke, "dev", "setup", str(run.root), "--editable-install", "--yes", "--json"],
        cwd=run.root,
    )
    if not dev.get("applied"):
        raise SmokeFailure("dev_setup_not_applied: inspect dev-setup capture and rerun")
    if not dev.get("editable_install", {}).get("ok"):
        raise SmokeFailure(
            "editable_install_failed: inspect dev-setup capture and repair its named dependency"
        )


def source_tests(run: SmokeRun) -> None:
    run_source_tests(run.root, run.commands)


def require_browser_installation(onboard: dict, capture: Path) -> None:
    """An already-provisioned runner cannot prove unattended package installation."""
    output = capture.read_text(encoding="utf-8")
    if onboard.get("browser_setup", {}).get("status") != "ready" or not all(
        proof in output
        for proof in (
            "installing missing Linux system libraries via passwordless sudo",
            "Linux system libraries verified",
        )
    ):
        raise SmokeFailure(
            "browser_installation_unproven: onboarding did not install and verify "
            "missing libraries through passwordless sudo. Run the product-smoke "
            "workflow with its disposable-runner missing-package fixture; "
            f"inspect {capture}."
        )


STAGES = (
    ("install", install),
    ("status", status),
    ("onboard", onboard),
    ("hooks", hooks),
    ("dev-setup", dev_setup),
    ("source-tests", source_tests),
)
STAGE_NAMES = tuple(name for name, _ in STAGES)
