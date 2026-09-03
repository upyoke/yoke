"""Read this machine's own relay, watcher, and diagnostic files for a session.

Everything here runs on the machine that wrote the files and answers exactly
one leased question: what do you hold for this session, and what is the tail
of one of those files. Nothing is written, nothing outside the three known
roots is opened, and the answer is capped in lines and again in bytes so a
single runaway log cannot become an unbounded control-plane write.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import stat
from typing import Any, Iterable, Mapping, Sequence

from yoke_contracts.session_control.evidence_fetch import (
    EVIDENCE_MAX_BYTES,
    EVIDENCE_TAIL_DEFAULT_LINES,
    EVIDENCE_TAIL_MAX_LINES,
    EvidenceKind,
)
from yoke_cli.config.session_relay_instance import RELAY_LOG_FILE_NAMES
from yoke_contracts.machine_config.scratch_roots import scratch_root_candidates
from yoke_harness.session_relay_native_diagnostics import (
    NativeDiagnosticError,
    native_diagnostic_path,
    read_native_diagnostic,
)
from yoke_harness.session_relay_runtime import RelayAdapterResult
from yoke_harness.session_relay_schedule import relay_state_dir


ADAPTER_REVISION = "session-evidence-v1"
WATCHER_CAPTURE_DIR_NAME = "watcher-captures"
#: Nothing this reader returns may be larger than one capped file's tail.
_READ_BUDGET_BYTES = EVIDENCE_MAX_BYTES * 4


@dataclass(frozen=True)
class EvidenceFile:
    """One readable machine-local file, named the way a caller selects it."""

    name: str
    kind: EvidenceKind
    path: Path
    size_bytes: int
    modified_at: str

    def as_entry(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "size_bytes": self.size_bytes,
            "modified_at": self.modified_at,
        }


def _stamp(seconds: float) -> str:
    return (
        datetime.fromtimestamp(seconds, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _describe(path: Path, kind: EvidenceKind, name: str) -> EvidenceFile | None:
    """Return a readable regular file's facts, or nothing at all."""
    try:
        details = path.lstat()
    except OSError:
        return None
    if not stat.S_ISREG(details.st_mode) or stat.S_ISLNK(details.st_mode):
        return None
    if details.st_uid != os.getuid():
        return None
    return EvidenceFile(
        name=name,
        kind=kind,
        path=path,
        size_bytes=int(details.st_size),
        modified_at=_stamp(details.st_mtime),
    )


def _relay_logs(state_dir: Path) -> list[EvidenceFile]:
    found = []
    for name in RELAY_LOG_FILE_NAMES:
        entry = _describe(state_dir / name, "relay", name)
        if entry is not None:
            found.append(entry)
    return found


def _watcher_captures(
    session_id: str,
    scratch_roots: Sequence[Path],
) -> list[EvidenceFile]:
    """Every capture under this session's own scratch subtree.

    Two segments are unknown to this process. The project segment above
    ``sessions/`` is resolved from the writing process's own configuration,
    and the scratch root itself is whichever candidate that process could
    write to — so the listing walks every project segment under every
    candidate root. A session id is unique across both, so this finds
    exactly the session's captures and nothing else.
    """
    found = []
    runs = [
        run
        for root in scratch_roots
        for run in root.glob(f"*/sessions/{session_id}/runs/*")
    ]
    for run in runs:
        directory = run / WATCHER_CAPTURE_DIR_NAME
        if not directory.is_dir():
            continue
        for capture in sorted(directory.iterdir()):
            entry = _describe(capture, "watcher", f"{run.name}/{capture.name}")
            if entry is not None:
                found.append(entry)
    return found


def _diagnostics(
    references: Iterable[str],
    state_dir: Path | None,
) -> list[EvidenceFile]:
    found = []
    for reference in references:
        try:
            path = native_diagnostic_path(reference, state_dir=state_dir, create=False)
        except NativeDiagnosticError:
            continue
        entry = _describe(path, "diagnostic", reference)
        if entry is not None:
            found.append(entry)
    return found


def list_session_evidence(
    session_id: str,
    *,
    kind: str | None,
    diagnostic_refs: Iterable[str] = (),
    state_dir: Path | None = None,
    scratch_root: Path | None = None,
) -> list[EvidenceFile]:
    """Return every file of the requested kinds, newest first."""
    directory = state_dir or relay_state_dir()
    roots = (scratch_root,) if scratch_root is not None else scratch_root_candidates()
    found: list[EvidenceFile] = []
    if kind in (None, "relay"):
        found.extend(_relay_logs(directory))
    if kind in (None, "watcher"):
        found.extend(_watcher_captures(session_id, roots))
    if kind in (None, "diagnostic"):
        found.extend(_diagnostics(diagnostic_refs, directory))
    return sorted(
        found, key=lambda entry: (entry.modified_at, entry.name), reverse=True
    )


def read_tail(
    entry: EvidenceFile,
    *,
    tail_lines: int,
    state_dir: Path | None = None,
) -> tuple[str, bool]:
    """Return the last *tail_lines* lines, re-capped in bytes, and whether cut.

    A diagnostic goes through its own owner-and-permission-checked reader so
    the private-capture rules that store it also govern reading it back.
    """
    lines = max(1, min(int(tail_lines), EVIDENCE_TAIL_MAX_LINES))
    if entry.kind == "diagnostic":
        raw = read_native_diagnostic(entry.name, state_dir=state_dir)
    else:
        with entry.path.open("rb") as stream:
            if entry.size_bytes > _READ_BUDGET_BYTES:
                stream.seek(entry.size_bytes - _READ_BUDGET_BYTES)
            raw = stream.read(_READ_BUDGET_BYTES)
    text = raw.decode("utf-8", errors="replace")
    kept = text.splitlines()[-lines:]
    body = "\n".join(kept)
    encoded = body.encode("utf-8")
    if len(encoded) <= EVIDENCE_MAX_BYTES:
        return body, len(encoded) < len(text.encode("utf-8"))
    return encoded[-EVIDENCE_MAX_BYTES:].decode("utf-8", errors="replace"), True


def _select(
    files: list[EvidenceFile],
    *,
    file_name: str | None,
) -> EvidenceFile | None:
    if file_name is None:
        return files[0] if files else None
    for entry in files:
        if entry.name == file_name:
            return entry
    return None


def read_session_evidence(
    job: Mapping[str, Any],
    *,
    state_dir: Path | None = None,
    scratch_root: Path | None = None,
) -> RelayAdapterResult:
    """Answer one leased evidence job from this machine's own filesystem."""
    request = job.get("evidence_request")
    request = request if isinstance(request, Mapping) else {}
    session_id = str(job.get("target_session_id") or "")
    kind = str(request.get("kind") or "") or None
    file_name = str(request.get("file_name") or "") or None
    references = [
        str(value) for value in (request.get("diagnostic_refs") or ()) if value
    ]
    try:
        files = list_session_evidence(
            session_id,
            kind=kind,
            diagnostic_refs=references,
            state_dir=state_dir,
            scratch_root=scratch_root,
        )
    except OSError as exc:
        return RelayAdapterResult(
            "unreadable",
            adapter_revision=ADAPTER_REVISION,
            evidence={"result_code": str(exc.strerror or "listing_failed")[:128]},
        )
    listing = [entry.as_entry() for entry in files]
    if not files:
        return RelayAdapterResult(
            "no_files",
            adapter_revision=ADAPTER_REVISION,
            document={"files": listing},
        )
    selected = _select(files, file_name=file_name)
    if selected is None:
        return RelayAdapterResult(
            "not_found",
            adapter_revision=ADAPTER_REVISION,
            document={"files": listing},
        )
    try:
        content, truncated = read_tail(
            selected,
            tail_lines=int(request.get("tail_lines") or EVIDENCE_TAIL_DEFAULT_LINES),
            state_dir=state_dir,
        )
    except (OSError, NativeDiagnosticError) as exc:
        return RelayAdapterResult(
            "unreadable",
            adapter_revision=ADAPTER_REVISION,
            evidence={"result_code": str(exc)[:128]},
            document={"files": listing, "selected_file": selected.name},
        )
    return RelayAdapterResult(
        "read",
        adapter_revision=ADAPTER_REVISION,
        document={
            "files": listing,
            "selected_file": selected.name,
            "content": content,
            "truncated": truncated,
        },
    )


__all__ = [
    "ADAPTER_REVISION",
    "WATCHER_CAPTURE_DIR_NAME",
    "EvidenceFile",
    "list_session_evidence",
    "read_session_evidence",
    "read_tail",
]
