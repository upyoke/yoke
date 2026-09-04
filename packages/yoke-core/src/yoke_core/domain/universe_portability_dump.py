"""Bounded private-file export for portable universe dumps."""

from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from yoke_core.domain import universe_archive_output
from yoke_core.domain.postgres_client_runtime import postgres_executable
from yoke_core.domain.source_authority_connect_policy import FENCE_STATE_SCHEMA
from yoke_core.domain.universe_portability_common import (
    DEFAULT_ARCHIVE_TIMEOUT_S,
    DEFAULT_MAX_ARCHIVE_BYTES,
    PUMP_CHUNK_BYTES,
    ArchiveInspection,
    ArchiveTooLargeError,
    UniversePortabilityError,
    bounded_diagnostic_reader,
    postgres_client_env,
    remaining_timeout,
    terminate,
)
from yoke_core.domain.universe_portability_inspection import inspect_archive


_log = logging.getLogger("yoke.universe.portability")
EXPORTED_SNAPSHOT_RE = re.compile(r"^[0-9A-Fa-f]+(?:-[0-9A-Fa-f]+)+$")


def dump_universe(
    dsn: str,
    destination: Path | str,
    *,
    max_bytes: int = DEFAULT_MAX_ARCHIVE_BYTES,
    timeout_s: int = DEFAULT_ARCHIVE_TIMEOUT_S,
    pg_dump: Optional[str] = None,
    snapshot: Optional[str] = None,
    executable_resolver: Callable[[str], str] = postgres_executable,
    client_env_builder: Callable[[str], dict[str, str]] = postgres_client_env,
    archive_inspector: Callable[..., ArchiveInspection] = inspect_archive,
) -> ArchiveInspection:
    """Create and inspect one portable dump, deleting every failed artifact."""
    dest = Path(destination)
    dest.parent.mkdir(parents=True, exist_ok=True)
    executable = pg_dump or executable_resolver("pg_dump")
    if snapshot is not None and EXPORTED_SNAPSHOT_RE.fullmatch(snapshot) is None:
        raise UniversePortabilityError("exported PostgreSQL snapshot id is invalid")
    client_env = client_env_builder(dsn)
    if snapshot is not None:
        client_env["PGAPPNAME"] = "yoke-universe-export-pg-dump"
    try:
        archive_output = universe_archive_output.prepare_private_archive_output(dest)
    except universe_archive_output.PrivateArchiveOutputError as exc:
        raise UniversePortabilityError(str(exc)) from exc
    deadline = time.monotonic() + timeout_s
    stderr_tail = bytearray()
    pump_errors: list[BaseException] = []
    try:
        argv = [
            executable,
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            "--no-comments",
            "--no-security-labels",
            "--exclude-table=public.capability_secrets",
            f"--exclude-schema={FENCE_STATE_SCHEMA}",
        ]
        if snapshot is not None:
            argv.append(f"--snapshot={snapshot}")
        process = subprocess.Popen(
            argv,
            env=client_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        archive_output.cleanup()
        raise UniversePortabilityError(
            f"universe export could not start: {exc}"
        ) from exc
    assert process.stdout is not None and process.stderr is not None
    workers = (
        threading.Thread(
            target=archive_pump,
            args=(process.stdout, archive_output),
            kwargs={"max_bytes": max_bytes, "errors": pump_errors},
            daemon=True,
        ),
        threading.Thread(
            target=bounded_diagnostic_reader,
            args=(process.stderr, stderr_tail),
            daemon=True,
        ),
    )
    for worker in workers:
        worker.start()
    try:
        process.wait(timeout=remaining_timeout(deadline, "export"))
        # Draining stdout and durably flushing the archive are part of the
        # export's end-to-end budget. A fixed grace period here can turn a
        # healthy pg_dump into a false timeout when the filesystem takes more
        # than a few seconds to fsync under load.
        workers[0].join(timeout=max(0.0, deadline - time.monotonic()))
        if workers[0].is_alive():
            raise subprocess.TimeoutExpired([executable], timeout_s)
    except subprocess.TimeoutExpired as exc:
        # Attribute the stall before terminate() destroys the evidence: a
        # still-running pg_dump points at the server or the network, while an
        # exited pg_dump with a live pump thread points at the archive write.
        phase = (
            "the archive write stalled after pg_dump exited"
            if process.poll() is not None
            else "pg_dump was still running"
        )
        elapsed = int(time.monotonic() - (deadline - timeout_s))
        terminate(process)
        archive_output.cleanup()
        # The kill closes the stderr pipe, so the diagnostic reader reaches
        # EOF; wait for it briefly so the logged tail is complete rather than
        # whatever the race left behind.
        workers[1].join(timeout=2)
        _log.error(
            "universe export timed out after %ss (%s; %ss elapsed);"
            " redacted stderr tail:\n%s",
            timeout_s,
            phase,
            elapsed,
            _redacted_stderr_tail(stderr_tail, client_env),
        )
        raise UniversePortabilityError(
            f"universe export timed out after {timeout_s}s"
            f" ({phase}; {elapsed}s elapsed)"
        ) from exc
    finally:
        terminate(process)
        for worker in workers:
            worker.join(timeout=5)
    if pump_errors:
        archive_output.cleanup()
        error = pump_errors[0]
        if isinstance(error, ArchiveTooLargeError):
            raise error
        raise UniversePortabilityError(
            "universe export stream failed before the archive completed"
        ) from error
    if process.returncode != 0:
        archive_output.cleanup()
        _log.error(
            "portable universe export failed rc=%s; redacted stderr tail:\n%s",
            process.returncode,
            _redacted_stderr_tail(stderr_tail, client_env),
        )
        raise UniversePortabilityError(
            "universe export failed; see the server log for the redacted"
            " pg_dump diagnostic"
        )
    try:
        inspection = archive_inspector(
            archive_output.temporary,
            max_bytes=max_bytes,
            timeout_s=remaining_timeout(deadline, "export"),
        )
        archive_output.commit()
        return inspection
    except UniversePortabilityError:
        archive_output.cleanup()
        raise
    except universe_archive_output.PrivateArchiveOutputError as exc:
        archive_output.cleanup()
        raise UniversePortabilityError(str(exc)) from exc


def _redacted_stderr_tail(
    stderr_tail: bytearray,
    client_env: dict[str, str],
) -> str:
    """The last stderr lines with the connection password scrubbed."""
    diagnostic = bytes(stderr_tail).decode("utf-8", errors="replace")
    password = client_env.get("PGPASSWORD", "")
    if password:
        diagnostic = diagnostic.replace(password, "<redacted-secret>")
    return "\n".join(diagnostic.strip().splitlines()[-12:]) or "<no stderr>"


def archive_pump(
    source: object,
    output: object,
    *,
    max_bytes: int,
    errors: list[BaseException],
) -> None:
    """Write pg_dump stdout to a private file with an in-flight ceiling."""
    written = 0
    try:
        with output as stream:
            while True:
                chunk = source.read(PUMP_CHUNK_BYTES)  # type: ignore[attr-defined]
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise ArchiveTooLargeError(
                        "the universe archive exceeds the"
                        f" {max_bytes}-byte safety limit"
                    )
                stream.write(chunk)
    except BaseException as exc:  # noqa: BLE001 - crosses a worker thread
        errors.append(exc)
    finally:
        source.close()  # type: ignore[attr-defined]


__all__ = ["EXPORTED_SNAPSHOT_RE", "archive_pump", "dump_universe"]
