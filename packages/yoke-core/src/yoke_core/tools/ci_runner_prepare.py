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


PG_CLIENT_BIN = Path("/usr/lib/postgresql/16/bin")
# initdb and postgres stay out: CI installs no embedded engine.
PG_CLIENT_TOOLS = ("pg_dump", "pg_restore", "psql", "createdb", "pg_isready")
PG_CLIENT_LIB = PG_CLIENT_BIN.parent / "lib"
PG_CLIENT_LOADER_CONF = "/etc/ld.so.conf.d/yoke-ci-pg-client.conf"
LDCONFIG_LOCK = "/var/lock/yoke-ci-ldconfig.lock"
IMAGE_LIB_TRIPLETS = {"x86_64": "x86_64-linux-gnu", "aarch64": "aarch64-linux-gnu"}


def _pg_client_step(stage: str, args: list[str], recovery: str, **kwargs):
    try:
        return _run(args, **kwargs)
    except PreparationError as exc:
        raise _refuse(f"ci_runner_pg_client_{stage}_failed: {exc}", recovery) from exc


def _pg_client_version_problem() -> str | None:
    """Return why the PostgreSQL 16 client tools are unusable, or None."""
    for tool in PG_CLIENT_TOOLS:
        path = PG_CLIENT_BIN / tool
        try:
            result = subprocess.run(
                [str(path), "--version"], capture_output=True, text=True,
                timeout=10, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return f"{path}: {exc}"
        words = result.stdout.split()
        if result.returncode != 0 or len(words) < 3 or not words[2].startswith("16."):
            return f"{path}: {(result.stdout + result.stderr).strip()[:400]}"
    return None


def _loader_finds_libpq() -> bool:
    cache = _pg_client_step(
        "loader", ["ldconfig", "-p"],
        "Repair the runner's loader cache (ldconfig), then retry CI",
        capture=True, timeout=10,
    )
    return any(line.split()[:1] == ["libpq.so.5"] for line in cache.stdout.splitlines())


def _copy_pg_client(image: str, holder: str, staging: Path) -> bool:
    """Copy the client tools (and libpq when missing) out of the image."""
    pull = "Check the pulled image and Docker daemon, then retry CI"
    triplet = IMAGE_LIB_TRIPLETS.get(platform.machine())
    if triplet is None:
        raise _refuse(
            f"ci_runner_pg_client_unsupported_arch: {platform.machine()}",
            "Run CI on an x86_64 or aarch64 runner, then retry CI",
        )
    sources = [(f"{PG_CLIENT_BIN}/{tool}", staging / tool) for tool in PG_CLIENT_TOOLS]
    needs_libpq = not _loader_finds_libpq()
    if needs_libpq:
        sources.append((f"/usr/lib/{triplet}/libpq.so.5", staging / "libpq.so.5"))
    _pg_client_step("create", ["docker", "create", "--name", holder, image], pull, timeout=60)
    try:
        for source, target in sources:
            _pg_client_step(
                "copy", ["docker", "cp", "-L", f"{holder}:{source}", str(target)],
                pull, timeout=60,
            )
    except PreparationError:
        try:
            _run(["docker", "rm", "-f", holder], timeout=30)
        except PreparationError as cleanup:
            print(str(cleanup), file=sys.stderr, flush=True)
        raise
    _pg_client_step(
        "cleanup", ["docker", "rm", "-f", holder],
        f"Remove container {holder} with docker rm -f, then retry CI", timeout=30,
    )
    return needs_libpq


def install_pg_client(image: str, container: str) -> None:
    """Supply PostgreSQL 16 client tools from the pulled server image, without apt."""
    if _pg_client_version_problem() is None:
        return
    if os.environ.get("RUNNER_ENVIRONMENT") != "github-hosted":
        raise _refuse(
            "ci_runner_pg_client_missing: PostgreSQL 16 " + ", ".join(PG_CLIENT_TOOLS)
            + f" in {PG_CLIENT_BIN}",
            "Install the PostgreSQL 16 client tools on the runner, then retry CI",
        )
    staging = Path(tempfile.mkdtemp(prefix="yoke-ci-pg-client.", dir="/tmp"))
    needs_libpq = _copy_pg_client(image, f"{container}-client", staging)
    install = "Repair sudo access and runner disk space, then retry CI"
    _pg_client_step("install", ["sudo", "install", "-d", str(PG_CLIENT_BIN)],
                    install, timeout=30)
    _pg_client_step("install", [
        "sudo", "install", "-m", "0755",
        *(str(staging / tool) for tool in PG_CLIENT_TOOLS), str(PG_CLIENT_BIN),
    ], install, timeout=30)
    if needs_libpq:
        _pg_client_step("install", [
            "sudo", "install", "-D", "-m", "0644",
            str(staging / "libpq.so.5"), str(PG_CLIENT_LIB / "libpq.so.5"),
        ], install, timeout=30)
        _pg_client_step("install", [
            "sudo", "sh", "-c", 'printf "%s\\n" "$1" > "$2"', "_",
            str(PG_CLIENT_LIB), PG_CLIENT_LOADER_CONF,
        ], install, timeout=10)
        _pg_client_step("loader", ["sudo", "flock", LDCONFIG_LOCK, "ldconfig"],
                        "Repair the runner's loader cache (ldconfig), then retry CI",
                        timeout=60)
    problem = _pg_client_version_problem()
    if problem:
        raise _refuse(
            f"ci_runner_pg_client_unusable: {problem}",
            "Check the copied tools' shared libraries with ldd, then retry CI",
        )


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
    install_pg_client(image, container)
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
