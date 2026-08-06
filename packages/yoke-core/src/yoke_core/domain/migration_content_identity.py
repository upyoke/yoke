"""Project-neutral comparison of migration history bytes with ledger evidence.

Migration names prove membership, but not that the bytes now shipped under a
permanent name are the bytes a database recorded.  This module adds that
second question without knowing whose history or ledger it is inspecting.
Callers supply both the history and a :class:`LedgerContract`.

Only non-NULL common rows are compared.  A NULL digest is legacy evidence that
requires explicit adoption, not a reason to stop an otherwise safe boot.  A
ledger row outside the packaged history remains the normal rollback shape and
is never compared with bytes an older artifact cannot possess.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable, Sequence, Tuple

from yoke_core.domain.migration_apply_contract import MigrationApplyError

if TYPE_CHECKING:
    from yoke_core.domain.migration_history import MigrationEntry
    from yoke_core.domain.migration_ledger_contract import LedgerContract


SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


def raw_content_sha256(content: bytes) -> str:
    """Return SHA256 over *content* exactly as stored, without normalization."""
    return hashlib.sha256(content).hexdigest()


@dataclass(frozen=True)
class ContentMismatch:
    """One common ledger/history row whose non-NULL digests disagree."""

    entry_name: str
    recorded_sha256: str
    packaged_sha256: str


@dataclass(frozen=True)
class ContentIdentityStatus:
    """The complete content-evidence state for one history and ledger."""

    verified: Tuple[str, ...]
    adoption_required: Tuple[str, ...]
    adoptable: Tuple[str, ...]
    mismatches: Tuple[ContentMismatch, ...]
    ledger_ahead: Tuple[str, ...]

    @property
    def content_matches(self) -> bool:
        return not self.mismatches


class MigrationContentMismatch(MigrationApplyError):
    """A recorded permanent entry names bytes other than those packaged."""


def compare_content_identities(
    history: Sequence[MigrationEntry],
    ledger_rows: Iterable[tuple[Any, Any]],
) -> ContentIdentityStatus:
    """Compare already-read ``(entry, digest)`` rows with *history*.

    NULL/blank digests are exposed as ``adoption_required``.  The ``adoptable``
    subset is present in this artifact's history and can therefore be proven by
    an artifact-bound manifest.  Rows outside history remain visible through
    ``ledger_ahead`` so rollback behavior is preserved.
    """
    known = {entry.name: entry for entry in history}
    verified: list[str] = []
    adoption_required: list[str] = []
    adoptable: list[str] = []
    mismatches: list[ContentMismatch] = []
    ledger_ahead: list[str] = []

    for raw_name, raw_digest in ledger_rows:
        name = str(raw_name)
        entry = known.get(name)
        digest = str(raw_digest).strip() if raw_digest is not None else ""
        if entry is None:
            ledger_ahead.append(name)
            if not digest:
                adoption_required.append(name)
            continue
        if not digest:
            adoption_required.append(name)
            adoptable.append(name)
            continue
        packaged = entry.content_sha256
        if not SHA256_PATTERN.fullmatch(digest) or digest.lower() != packaged:
            mismatches.append(
                ContentMismatch(
                    entry_name=name,
                    recorded_sha256=digest,
                    packaged_sha256=packaged,
                )
            )
            continue
        verified.append(name)

    return ContentIdentityStatus(
        verified=tuple(verified),
        adoption_required=tuple(adoption_required),
        adoptable=tuple(adoptable),
        mismatches=tuple(mismatches),
        ledger_ahead=tuple(ledger_ahead),
    )


def read_content_identity_status(
    conn: Any,
    history: Sequence[MigrationEntry],
    ledger: LedgerContract,
) -> ContentIdentityStatus:
    """Read *ledger* using only its declared identifiers, then compare."""
    rows = conn.execute(
        f"SELECT {ledger.entry_column}, {ledger.digest_column} "
        f"FROM {ledger.table} ORDER BY {ledger.entry_column}"
    ).fetchall()
    return compare_content_identities(history, rows)


def require_matching_content_identity(
    conn: Any,
    history: Sequence[MigrationEntry],
    ledger: LedgerContract,
) -> ContentIdentityStatus:
    """Return status or fail before a caller restores or mutates anything."""
    status = read_content_identity_status(conn, history, ledger)
    if not status.mismatches:
        return status
    detail = "; ".join(
        f"{item.entry_name}: ledger={item.recorded_sha256!r} "
        f"packaged={item.packaged_sha256!r}"
        for item in status.mismatches
    )
    raise MigrationContentMismatch(
        "migration content identity mismatch; permanent history bytes differ "
        "from recorded ledger evidence: " + detail
    )


__all__ = [
    "ContentIdentityStatus",
    "ContentMismatch",
    "MigrationContentMismatch",
    "SHA256_PATTERN",
    "compare_content_identities",
    "raw_content_sha256",
    "read_content_identity_status",
    "require_matching_content_identity",
]
