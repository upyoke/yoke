"""Reuse existing teardown commands and retain recovery state on failure."""

from __future__ import annotations

from collections.abc import Callable
import json
import shutil
import subprocess
import sys
from pathlib import Path

from yoke_cli.config import machine_uninstall_detached, machine_uninstall_workers
from yoke_cli.config.machine_uninstall_inventory import Inventory, UninstallError
from yoke_cli.config.machine_config_file import remove_file
from yoke_contracts.self_host_bootstrap_output import redact_api_tokens

COMMAND_TIMEOUT_SECONDS = 300
NOT_REMOVED = (
    "Not removed: uv, the PATH line in your shell profile, the Yoke GitHub App "
    "(remove it in GitHub settings). Push the project-uninstall commits in your chosen checkouts."
)


def command(args: list[str]) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "yoke_cli.main", *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=COMMAND_TIMEOUT_SECONDS,
    )
    if result.returncode:
        detail = redact_api_tokens((result.stderr or result.stdout).strip()[-2048:])
        raise UninstallError(
            f"uninstall_command_failed: yoke {' '.join(args)} (exit {result.returncode}); "
            f"{detail}. Repair this step and retry uninstall."
        )
    if result.stderr.strip():
        print(redact_api_tokens(result.stderr.strip()), file=sys.stderr)
    if "export" in args or args[:2] == ["self-host", "teardown"]:
        print(redact_api_tokens(result.stdout.strip()))
    elif args[:2] == ["project", "uninstall"]:
        report = json.loads(result.stdout)
        for warning in report.get("warnings", []):
            print(f"project uninstall: {warning}")


def back_up(inventory: Inventory, emit: Callable[[str], None]) -> None:
    targets = (
        [("local universe", inventory.local_env)] if inventory.local_universe else []
    )
    targets += [(f"self-host {directory}", env) for directory, env in inventory.bundles]
    # No automatic backup and no artifact inside the home about to be deleted.
    output = Path.cwd().resolve()
    if output == inventory.home.resolve() or inventory.home.resolve() in output.parents:
        raise UninstallError(
            "uninstall_backup_inside_home: run uninstall from a directory outside "
            "the machine home so its exports survive removal."
        )
    failures = []
    for label, env in targets:
        try:
            if not env:
                raise UninstallError(
                    "uninstall_backup_connection_missing: restore the machine connection "
                    "to this universe, then retry with --backup."
                )
            command(["--env", env, "universe", "export", "--out", str(output) + "/"])
            emit(f"backup {label}: done (archive in {output})")
        except Exception as exc:
            failures.append(label)
            emit(f"backup {label}: failed ({type(exc).__name__}: {exc})")
    if failures:
        raise UninstallError(
            "uninstall_backup_failed: nothing was uninstalled. Repair the failed "
            "export and retry --backup, or explicitly choose --no-backup."
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

    # Remove the supervisor first so it cannot launch another worker during teardown.
    for env in inventory.relay_envs:
        attempt(
            f"relay {env}",
            lambda env=env: command(["--env", env, "relay", "uninstall"]),
        )
    if not inventory.relay_envs:
        skipped("relay", "no eligible machine connections")
    attempt("workers", lambda: machine_uninstall_workers.stop(inventory.relay_envs))
    for checkout in inventory.projects:
        if checkout in selected:
            attempt(
                f"project {checkout}",
                lambda checkout=checkout: command(
                    [
                        "project",
                        "uninstall",
                        str(checkout),
                        "--config",
                        str(inventory.config),
                    ]
                ),
            )
        else:
            skipped(f"project {checkout}", "operator retained the project layer")
    if not inventory.projects:
        skipped("projects", "no installed registered checkouts")
    if inventory.config.is_file():
        attempt(
            "GitHub",
            lambda: command(
                ["github", "disconnect", "--config", str(inventory.config)]
            ),
        )
    else:
        skipped("GitHub", "no machine config")
    attempt("local UI", lambda: command(["ui", "down"]))
    if inventory.local_universe:
        attempt("local Postgres", lambda: command(["local-postgres", "stop"]))
    else:
        skipped("local Postgres", "no embedded universe")
    for directory, _env in inventory.bundles:
        attempt(
            f"self-host {directory}",
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
    if inventory.discovery_error:
        attempt("self-host discovery", lambda: _fail(inventory.discovery_error))
    elif not inventory.bundles:
        skipped("self-host", "no local self-host server")
    if counts["failed"]:
        skipped("machine home", "retained for recovery from failed cleanup")
        skipped("CLI", "retained for recovery from failed cleanup")
    else:
        # Prepare the detached worker before deleting anything it needs; a failed
        # spawn must leave the installed CLI and its config available for recovery.
        try:
            finish = machine_uninstall_detached.prepare()
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
                            f"CLI: handed off (removes yoke-cli after this process exits; log: {finish.log})"
                        )
    emit(
        f"Uninstall summary: {counts['done']} done, {counts['skipped']} skipped, {counts['failed']} failed."
    )
    emit(NOT_REMOVED)
    return 1 if counts["failed"] else 0


def _fail(message: str) -> None:
    raise UninstallError(message)


def _remove_home(home: Path) -> None:
    if home.exists():
        shutil.rmtree(home)
