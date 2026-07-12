"""Fresh-database restore entrypoint for self-host universe imports.

The host-side ``yoke self-host import`` adapter streams a portable archive
into this module's stdin inside the server image.  The archive is staged in
an owner-only temporary file because ``pg_restore`` requires a seekable input.
The trusted portability restore owns schema validation and data loading; this
module adds the destination-specific credential handoff before that restore
transaction commits.

Hosted credentials are intentionally non-portable: archives contain only
their hashes, while the raw values remain with the departing platform.  Every
active imported token is therefore revoked and one fresh org-admin token is
minted atomically with the data restore.  The raw replacement is emitted once
in the success JSON and is never persisted.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from typing import BinaryIO, Optional, Sequence

import psycopg

from yoke_core.domain import (
    db_backend,
    json_helper,
    universe_import_credentials,
    universe_portability,
    universe_startup_lock,
)


_READ_BYTES = 1 << 20


class UniverseImportError(RuntimeError):
    """A self-host import could not establish a usable destination."""


def _stage_archive(stream: BinaryIO, *, max_bytes: int) -> Path:
    """Copy stdin to one private seekable file under a hard size ceiling."""
    descriptor, raw_path = tempfile.mkstemp(
        prefix="yoke-self-host-import-",
        suffix=".dump",
    )
    path = Path(raw_path)
    try:
        os.fchmod(descriptor, 0o600)
        total = 0
        with os.fdopen(descriptor, "wb") as destination:
            descriptor = -1
            while True:
                chunk = stream.read(min(_READ_BYTES, max_bytes - total + 1))
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise universe_portability.ArchiveTooLargeError(
                        "the streamed universe archive exceeds the "
                        f"{max_bytes}-byte import limit"
                    )
                destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def import_from_stream(
    stream: BinaryIO,
    *,
    dsn: Optional[str] = None,
    max_bytes: int = universe_portability.DEFAULT_MAX_ARCHIVE_BYTES,
) -> dict[str, object]:
    """Restore one stdin archive and return the one-time credential payload."""
    archive = _stage_archive(stream, max_bytes=max_bytes)
    credential: universe_import_credentials.ImportedCredential | None = None

    def finalize(conn: psycopg.Connection) -> None:
        nonlocal credential
        credential = universe_import_credentials.replace_imported_credentials(conn)

    resolved_dsn = dsn or db_backend.resolve_pg_dsn()
    try:
        with universe_startup_lock.exclusive_import_guard(resolved_dsn):
            inspection = universe_portability.restore_universe(
                archive,
                resolved_dsn,
                max_bytes=max_bytes,
                finalize=finalize,
            )
    finally:
        archive.unlink(missing_ok=True)
    if credential is None:
        raise UniverseImportError(
            "the restore completed without creating an admin credential"
        )
    return {
        "ok": True,
        "org": credential.org_slug,
        "actor_id": credential.actor_id,
        "token_id": credential.token_id,
        "raw_token": credential.raw_token,
        "revoked_token_count": credential.revoked_token_count,
        "revoked_web_session_count": credential.revoked_web_session_count,
        "archive": {
            "bytes": inspection.size_bytes,
            "dumped_from_postgres": inspection.dumped_from_postgres,
            "dumped_by_pg_dump": inspection.dumped_by_pg_dump,
            "table_entries": inspection.table_entries,
        },
    }


def recover_credential(*, dsn: Optional[str] = None) -> dict[str, object]:
    """Atomically revoke lost import credentials and mint a repeatable one."""
    resolved_dsn = dsn or db_backend.resolve_pg_dsn()
    with universe_startup_lock.exclusive_import_guard(resolved_dsn):
        conn = db_backend.connect_psycopg(resolved_dsn)
        try:
            credential = universe_import_credentials.recover_import_credential(conn)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
    return {
        "ok": True,
        "org": credential.org_slug,
        "actor_id": credential.actor_id,
        "token_id": credential.token_id,
        "raw_token": credential.raw_token,
        "revoked_token_count": credential.revoked_token_count,
        "revoked_web_session_count": credential.revoked_web_session_count,
        "mode": "credential-recovery",
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="universe_import_cli")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--stdin",
        action="store_true",
        help="Read the custom-format universe archive from stdin.",
    )
    mode.add_argument(
        "--recover-credential",
        action="store_true",
        help="Revoke prior import/recovery tokens and mint a fresh admin token.",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        # Trusted schema initializers retain a few legacy stdout progress
        # lines. Keep the container protocol's stdout as exactly one JSON
        # result so the host never has to search mixed output for a secret.
        with redirect_stdout(sys.stderr):
            result = (
                recover_credential()
                if args.recover_credential
                else import_from_stream(sys.stdin.buffer)
            )
    except universe_portability.UniversePortabilityError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except UniverseImportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except universe_import_credentials.UniverseImportCredentialError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except universe_startup_lock.UniverseStartupBusy as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (OSError, psycopg.Error):
        print(
            "error: the self-host destination database restore failed", file=sys.stderr
        )
        return 1
    except Exception:
        print(
            "error: the self-host destination database restore failed", file=sys.stderr
        )
        return 1
    print(json_helper.dumps_compact(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "UniverseImportError",
    "import_from_stream",
    "main",
    "recover_credential",
]
