"""Reuse existing teardown commands and retain recovery state on failure.

Beside the per-project layers, uninstall removes what Yoke wrote into each
harness's user-level config: its machine-wide hooks with their Codex trust,
and every approval-posture and folder-trust setting
:mod:`yoke_contracts.harness_settings_ledger` records.
"""

from __future__ import annotations

from yoke_contracts.github_app_tokens import github_configurations

from collections.abc import Callable
import json
import os
import subprocess
import sys
from pathlib import Path

from yoke_cli.config import machine_uninstall_detached, machine_uninstall_workers
from yoke_cli.config import machine_config, machine_uninstall_projects, machine_uninstall_relays
from yoke_cli.config import machine_uninstall_browsers
from yoke_cli.config.machine_uninstall_inventory import Inventory, UninstallError
from yoke_cli.config.machine_config_file import remove_file
from yoke_contracts import harness_settings_ledger, harness_settings_revert
from yoke_contracts.platform_fs import remove_tree
from yoke_contracts.self_host_bootstrap_output import redact_api_tokens
from yoke_cli.hook_resident_lifecycle import stop_resident

COMMAND_TIMEOUT_SECONDS = 300
NOT_REMOVED = (
    "Not removed: uv, user-owned PATH entries, the Yoke GitHub App "
    "(remove it in GitHub settings), strategy documents under each project's "
    ".yoke/strategy (commit or delete them). Push the project-uninstall commits "
    "in your chosen checkouts."
)
# uv's documented uninstall; it also removes every other uv tool and Python.
UV_REMOVAL = (
    "Remove uv too only if nothing else uses it: "
    + (
        'uv cache clean; rm -r "$(uv python dir)" "$(uv tool dir)"; '
        "rm $HOME\\.local\\bin\\uv.exe $HOME\\.local\\bin\\uvx.exe $HOME\\.local\\bin\\uvw.exe "
        "(PowerShell)"
        if sys.platform == "win32"
        else 'uv cache clean && rm -r "$(uv python dir)" "$(uv tool dir)" && '
        'rm -rf ~/.config/uv && rm "$(command -v uv)" "$(command -v uvx)"'
    )
)


def command(args: list[str], *, forward_stderr: bool = True) -> str:
    """Run one CLI step; return its stdout, or raise its named failure.

    A failure always carries the child's stderr; ``forward_stderr=False``
    keeps a successful child's progress lines off the operator's terminal.
    """
    result = subprocess.run(
        [sys.executable, "-m", "yoke_cli.main", *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    warnings = _project_warnings(args, result.stdout)
    if result.returncode:
        detail = redact_api_tokens(
            "; ".join(warnings) or (result.stderr or result.stdout).strip()[-2048:]
        )
        raise UninstallError(
            f"uninstall_command_failed: yoke {' '.join(args)} (exit {result.returncode}); "
            f"{detail}. Repair this step and retry uninstall."
        )
    if forward_stderr and result.stderr.strip():
        print(redact_api_tokens(result.stderr.strip()), file=sys.stderr)
    if args[:2] == ["self-host", "teardown"]:
        print(redact_api_tokens(result.stdout.strip()))
    for warning in warnings:
        print(f"project uninstall: {redact_api_tokens(warning)}")
    return result.stdout


def _project_warnings(args: list[str], stdout: str) -> list[str]:
    """Read the named reasons from a project uninstall JSON report."""
    if args[:2] != ["project", "uninstall"]:
        return []
    try:
        report = json.loads(stdout)
    except ValueError:
        return []
    return list(report.get("warnings") or []) if isinstance(report, dict) else []


def _remove_machine_hooks(emit: Callable[[str], None]) -> None:
    """Strip every harness's machine-wide hooks, naming each outcome."""
    from yoke_harness.hooks.machine_hooks import MachineHooksError, remove_machine_hooks

    results = remove_machine_hooks()
    emit("machine-wide hooks: " + "; ".join(result.line() for result in results))
    failed = [result.detail for result in results if result.failed]
    if failed:
        raise MachineHooksError("; ".join(failed))


def _report_windows_path(emit: Callable[[str], None]) -> None:
    if sys.platform == "win32":
        from yoke_contracts.shell_path_state import tool_bin_dir
        from yoke_contracts.windows_user_path import (
            USER_PATH_LOCATION,
            contains,
            read_user_path,
        )

        present = contains(read_user_path(), tool_bin_dir(), os.environ)
        emit(
            f"Windows user PATH ({USER_PATH_LOCATION}): uv bin entry "
            + (
                "retained because uv owns it"
                if present
                else "absent; other entries retained"
            )
        )


def remove(
    inventory: Inventory, selected: tuple[Path, ...], emit: Callable[[str], None]
) -> int:
    counts = {"done": 0, "skipped": 0, "failed": 0}

    def skipped(label: str, reason: str) -> None:
        counts["skipped"] += 1
        emit(f"{label}: skipped ({reason})")

    def attempt(label: str, action: Callable[[], object]) -> None:
        try:
            action()
        except Exception as exc:
            counts["failed"] += 1
            emit(
                f"{label}: failed (uninstall_step_failed: {type(exc).__name__}: "
                f"{redact_api_tokens(str(exc))}; repair this step and retry uninstall)"
            )
        else:
            counts["done"] += 1
            emit(f"{label}: done")

    # A running Yoke browser keeps its Chromium in the machine home open, so
    # close them before anything changes, or stop with everything in place.
    attempt("browsers", lambda: machine_uninstall_browsers.stop(emit))
    if counts["failed"]:
        skipped("remaining steps", "a Yoke browser is still running; nothing else changed")
        emit(
            f"Uninstall summary: {counts['done']} done, {counts['skipped']} skipped, {counts['failed']} failed."
        )
        return 1
    # A project step that would refuse stops everything before anything changes.
    refusals = machine_uninstall_projects.preflight(inventory, selected, command)
    if refusals:
        counts["failed"] += len(refusals)
        for line in refusals:
            emit(line)
        skipped("remaining steps", "a project would refuse uninstall; nothing else changed")
        emit(
            f"Uninstall summary: {counts['done']} done, {counts['skipped']} skipped, {counts['failed']} failed."
        )
        return 1
    # Remove the supervisor first so it cannot launch another worker during teardown.
    for env in inventory.relay_envs:
        attempt(
            f"relay {env}",
            lambda env=env: command(["--env", env, "relay", "uninstall"]),
        )
    if not inventory.relay_envs:
        skipped("relay", "no eligible machine connections")
    if sys.platform in {"darwin", "linux", "win32"}:
        attempt(
            "saved relay services",
            lambda: machine_uninstall_relays.remove_saved_services(inventory.home),
        )
    attempt("workers", lambda: machine_uninstall_workers.stop(inventory.relay_envs))
    before_projects = counts["failed"]
    for checkout in inventory.projects:
        if checkout in selected:
            attempt(
                f"project {checkout}",
                lambda checkout=checkout: command(
                    machine_uninstall_projects.project_args(checkout, inventory)
                ),
            )
        else:
            skipped(f"project {checkout}", "operator retained the project layer")
    if not inventory.projects:
        skipped("projects", "no installed registered checkouts")
    # A failed project step's retry asks the server that owns it.
    keep_servers = counts["failed"] > before_projects
    github_skip = _github_skip_reason(inventory.config)
    if github_skip is None:
        payload = machine_config.load_config(inventory.config)
        for prefix in github_configurations(payload):
            env = prefix.removeprefix("connection_github.")
            args = ["--env", env] if prefix != "github" else []
            attempt(
                f"GitHub {env}",
                lambda args=args: command(
                    [*args, "github", "disconnect", "--config", str(inventory.config)]
                ),
            )
    else:
        skipped("GitHub", github_skip)
    attempt("machine-wide hooks", lambda: _remove_machine_hooks(emit))
    # The record of what Yoke wrote lives in the machine home, so this runs
    # before the home is deleted and a failure keeps both for the retry.
    if harness_settings_ledger.ledger_path().is_file():
        attempt("harness settings", lambda: _revert_harness_settings(emit))
    else:
        skipped("harness settings", "none recorded as written by Yoke")
    if sys.platform == "win32":
        attempt("Windows user PATH", lambda: _report_windows_path(emit))
    attempt("hook evaluator", stop_resident)
    attempt("local UI", lambda: command(["ui", "down"]))
    kept = "kept: a project step failed and its retry needs this server"
    if inventory.local_universe and keep_servers:
        skipped("local Postgres", kept)
    elif inventory.local_universe:
        attempt("local Postgres", lambda: command(["local-postgres", "stop"]))
    else:
        skipped("local Postgres", "no embedded universe")
    for directory, _env in inventory.bundles:
        if keep_servers:
            skipped(f"self-host {directory}", kept)
            continue
        attempt(
            f"self-host {directory} (its connection goes with the machine home)",
            lambda directory=directory: command(
                [
                    "self-host",
                    "teardown",
                    "--dir",
                    str(directory),
                    "--destroy-universe",
                    "--remove-images",
                    "--remove-bundle",
                    "--keep-connection",
                    "--yes",
                ]
            ),
        )
    for directory in inventory.wsl_bundles:
        skipped(
            f"self-host {directory}",
            "hosted in WSL; tear it down from WSL with "
            f"`yoke self-host teardown --dir {directory}`",
        )
    if inventory.discovery_error:
        attempt("self-host discovery", lambda: _fail(inventory.discovery_error))
    elif not inventory.bundles and not inventory.wsl_bundles:
        skipped("self-host", "no local self-host server")
    if counts["failed"]:
        skipped("machine home", "retained for recovery from failed cleanup")
        skipped("CLI", "retained for recovery from failed cleanup")
    else:
        # Prepare the detached worker before deleting anything it needs; a failed
        # spawn must leave the installed CLI and its config available for recovery.
        try:
            finish = machine_uninstall_detached.prepare(inventory.home)
        except Exception as exc:
            diagnostic = str(exc)
            attempt("CLI handoff", lambda: _fail(diagnostic))
            skipped("machine home", "CLI handoff failed; retained for recovery")
        else:
            if (
                inventory.config.is_file()
                and inventory.home not in inventory.config.parents
            ):
                attempt(
                    "external machine config", lambda: remove_file(inventory.config)
                )
            if counts["failed"]:
                skipped("machine home", "external config removal failed")
                finish.cancel()
                skipped("CLI", "external config removal failed")
            else:
                attempt("machine home", lambda: _remove_home(inventory.home))
                if counts["failed"]:
                    finish.cancel()
                    skipped("CLI", "machine home removal failed")
                else:
                    attempt("CLI handoff", finish.arm)
                    if counts["failed"]:
                        finish.cancel()
                    else:
                        emit(
                            f"CLI: handed off (removes yoke-cli at {finish.releases} and its PATH blocks after this process exits; a failure keeps its log at {finish.log})"
                        )
    emit(
        f"Uninstall summary: {counts['done']} done, {counts['skipped']} skipped, {counts['failed']} failed."
    )
    emit(NOT_REMOVED)
    emit(UV_REMOVAL)
    return 1 if counts["failed"] else 0


def _fail(message: str) -> None:
    raise UninstallError(message)


def _revert_harness_settings(emit: Callable[[str], None]) -> None:
    lines, failures = harness_settings_revert.revert_recorded()
    for line in lines:
        emit(f"harness settings: {line}")
    if failures:
        raise UninstallError(
            "uninstall_harness_settings_failed: " + "; ".join(failures) + ". "
            "Repair those files and retry uninstall; the record of what Yoke "
            "wrote stays in the machine home until then."
        )


def _github_skip_reason(config: Path) -> str | None:
    if not config.is_file():
        return "no machine config"
    if not github_configurations(machine_config.load_config(config)):
        return "no GitHub connection"
    payload = machine_config.load_config(config)
    connections = payload.get("connections") or {}
    if not connections or payload.get("active_env") not in connections:
        return "machine setup has no active connection"
    return None


def _remove_home(home: Path) -> None:
    if home.exists():
        remove_tree(home)
