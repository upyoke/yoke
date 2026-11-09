"""Overlap independent CI setup, joining every task before admitting tests.

This module and its imports need only the standard library: dependencies are
being installed concurrently. Call it with the checkout's package PYTHONPATH.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path
import platform
import random
import subprocess
import sys
import tempfile
import time

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.domain.pytest_cluster_identity import DISPOSABLE_SERVER_SETTINGS


class PreparationError(RuntimeError):
    """A bounded setup task failed with its recovery already attached."""


def _refuse(reason: str, recovery: str) -> PreparationError:
    return PreparationError(compose_refusal(reason, recovery=recovery))


def _run(args: list[str], *, capture: bool = False, timeout: int = 180):
    try:
        return subprocess.run(
            args, check=True, text=True, capture_output=capture, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise _refuse(
            f"ci_runner_setup_command_failed: {args[0]}: {exc}",
            "Inspect this task's command output, repair the runner or endpoint, then retry CI",
        ) from exc


def prepare_prerequisites() -> None:
    query = subprocess.run(
        ["dpkg-query", "-W", "-f=${Status}", "postgresql-client-16"],
        capture_output=True, text=True, timeout=10, check=False,
    )
    if query.returncode == 0 and query.stdout == "install ok installed":
        return
    if os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        raise _refuse(
            "ci_runner_prerequisites_missing: postgresql-client-16",
            "Install these packages from PGDG on the runner, then retry CI",
        )
    _run(["sudo", "install", "-d", "/usr/share/postgresql-common/pgdg"])
    key = "/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc"
    try:
        _run([
            "sudo", "curl", "--fail", "--silent", "--show-error", "--location",
            "--retry", "5", "--retry-all-errors", "--retry-max-time", "300",
            "--connect-timeout", "10", "--max-time", "60",
            "https://www.postgresql.org/media/keys/ACCC4CF8.asc", "-o", key,
        ], timeout=360)
    except PreparationError as exc:
        raise _refuse(
            "ci_runner_pgdg_key_download_failed: bounded download retries exhausted",
            "Check PostgreSQL key endpoint connectivity, then retry CI",
        ) from exc
    codename = platform.freedesktop_os_release()["VERSION_CODENAME"]
    source = (
        f"deb [signed-by={key}] https://apt.postgresql.org/pub/repos/apt "
        f"{codename}-pgdg main\n"
    )
    try:
        subprocess.run(
            ["sudo", "tee", "/etc/apt/sources.list.d/pgdg.list"], input=source,
            text=True, stdout=subprocess.DEVNULL, check=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise _refuse(
            "ci_runner_pgdg_source_failed: could not write the PGDG apt source",
            "Repair sudo access and apt source permissions, then retry CI",
        ) from exc
    _run(["sudo", "apt-get", "-o", "Acquire::Retries=3", "update"])
    _run([
        "sudo", "apt-get", "-o", "Acquire::Retries=3", "install", "--yes",
        "--no-install-recommends", "postgresql-client-16",
    ])


def install_dependencies() -> None:
    _run(["uv", "sync", "--all-packages", "--locked"])


def _publish_env(values: dict[str, str]) -> None:
    with Path(os.environ["GITHUB_ENV"]).open("a") as target:
        target.writelines(f"{key}={value}\n" for key, value in values.items())


def _start_container(args: list[str], container: str) -> None:
    for attempt in range(2):
        try:
            _run(args, timeout=120)
            return
        except PreparationError:
            if attempt == 0:
                try:
                    _run(["docker", "rm", "-f", container], timeout=30)
                except PreparationError as exc:
                    print(str(exc), file=sys.stderr, flush=True)
                continue
            for command in (
                ["docker", "ps", "-a", "--filter", f"name={container}"],
                ["docker", "logs", "--tail", "50", container],
                ["docker", "info"],
            ):
                print("CI Postgres diagnostic: " + " ".join(command),
                      file=sys.stderr, flush=True)
                try:
                    result = _run(command, capture=True, timeout=10)
                    print((result.stdout or "")[:8000], file=sys.stderr, flush=True)
                    print((result.stderr or "")[:8000], file=sys.stderr, flush=True)
                except PreparationError as exc:
                    print(str(exc), file=sys.stderr, flush=True)
            raise


def start_postgres() -> None:
    container = os.environ["PG_CONTAINER"]
    image = os.environ["POSTGRES_IMAGE"]
    socket_dir = tempfile.mkdtemp(prefix="yoke-ci-pg.", dir="/tmp")
    # Publish before starting Docker so the caller's always-cleanup can run
    # even if this task or a concurrent prerequisite fails.
    _publish_env({"YOKE_PG_SOCKET_DIR": socket_dir})
    for attempt in range(5):
        try:
            _run(["docker", "pull", image], timeout=60)
            break
        except PreparationError:
            if attempt == 4:
                raise _refuse(
                    "ci_runner_postgres_pull_failed: bounded image pulls exhausted",
                    "Check GHCR connectivity and runner disk space, then retry CI",
                ) from None
            # artifact-fetch-allow: bounded retries for transient GHCR transport faults
            time.sleep(random.randint(5, 30))
    timezone = dict(DISPOSABLE_SERVER_SETTINGS)["timezone"]
    _start_container([
        "docker", "run", "-d", "--name", container,
        "-v", f"{socket_dir}:/var/run/postgresql",
        "-e", "POSTGRES_USER=yoke", "-e", "POSTGRES_PASSWORD=yoke",
        "-e", "POSTGRES_DB=postgres", "-p", "5432", image,
        "-c", f"timezone={timezone}", "-c", "fsync=off",
        "-c", "synchronous_commit=off", "-c", "full_page_writes=off",
        "-c", "wal_level=minimal", "-c", "max_wal_senders=0",
    ], container)
    mapping = _run(["docker", "port", container, "5432"], capture=True, timeout=10)
    lines = mapping.stdout.splitlines()
    port = lines[0].rsplit(":", 1)[-1] if lines else ""
    if not port.isdecimal() or not 0 < int(port) < 65536:
        raise _refuse(
            "ci_runner_postgres_port_missing: Docker returned no valid host port",
            "Inspect the named container's port mapping, then retry CI",
        )
    _publish_env({
        "YOKE_PG_DSN": f"host=localhost port={port} user=yoke password=yoke dbname=postgres",
    })


def prepare() -> None:
    tasks = {
        "prerequisites": prepare_prerequisites,
        "dependencies": install_dependencies,
        "postgres": start_postgres,
    }
    failures = []
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
        pending = {executor.submit(task): name for name, task in tasks.items()}
        for future in as_completed(pending):
            name = pending[future]
            outcome = "passed"
            try:
                future.result()
            except Exception as exc:
                outcome = "failed"
                failures.append(f"{name}: {exc}")
                print(f"CI setup task failed: {name}: {exc}", file=sys.stderr, flush=True)
            print(
                f"CI setup task completed: {name}; outcome={outcome}; "
                f"elapsed={time.monotonic() - started:.3f}s", flush=True,
            )
    if failures:
        raise _refuse(
            "ci_runner_setup_failed: " + "; ".join(failures),
            "Repair each named task using its output and recovery, then retry CI; tests did not start",
        )


def main() -> int:
    try:
        prepare()
    except PreparationError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
