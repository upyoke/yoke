"""Reading a machine's own relay and watcher files from any other seat.

Relay diagnostics, watcher captures, and the relay's own service logs are
written to the machine that produced them and nowhere else. A seat on a
different machine could therefore see *that* a launch or a wake failed and
never see *why*, which is the half an operator actually needs.

The fetch closes that gap without moving any of those files: the control
plane asks the owning machine's relay, over the same machine-keyed job
routing that carries wakes and launch batches, for the tail of one named
file. Everything here is read-only and bounded twice — by a line count the
caller may raise only to :data:`EVIDENCE_TAIL_MAX_LINES`, and by a hard byte
cap the relay applies whatever line count it was handed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


EvidenceKind = Literal["relay", "watcher", "diagnostic"]
#: Every kind of machine-local file a relay will read back for a session.
EVIDENCE_KINDS: tuple[EvidenceKind, ...] = ("relay", "watcher", "diagnostic")

EVIDENCE_TAIL_DEFAULT_LINES = 200
EVIDENCE_TAIL_MAX_LINES = 2000
#: The relay truncates to this many bytes however many lines were asked for,
#: so one enormous line cannot become an unbounded control-plane write.
EVIDENCE_MAX_BYTES = 64 * 1024
#: How long the caller's own dispatch may wait for the owning relay to answer.
#: Beyond this the request stays pending and the same command reads it back.
EVIDENCE_WAIT_DEFAULT_SECONDS = 10
EVIDENCE_WAIT_MAX_SECONDS = 30
#: A request no relay leased within this window is expired rather than left
#: to be served long after the person who asked for it walked away.
EVIDENCE_REQUEST_TTL_SECONDS = 300
#: How long one leased evidence read may run before the lease is released.
EVIDENCE_LEASE_SECONDS = 60

EVIDENCE_RESULT_CODES = frozenset(
    {
        # The relay read the selected file and reported its tail.
        "read",
        # The relay holds nothing at all for this session and kind.
        "no_files",
        # The named file or diagnostic reference is not on this machine.
        "not_found",
        # The file is there and the relay could not read it safely.
        "unreadable",
    }
)
_SUCCESS_RESULTS = frozenset({"read", "no_files"})


def evidence_result_succeeded(result_code: str) -> bool:
    """Whether a reported code answered the question rather than failing it."""
    return result_code in _SUCCESS_RESULTS


def evidence_pull_command(
    session_id: str,
    evidence_id: str | None = None,
) -> str:
    """Return the any-seat recipe that reads this session's machine-local files.

    Fleet-report rows and attempt summaries name a session whose diagnosis
    lives on another machine. This is the one command that brings it back, so
    every such row renders it from here rather than composing its own.
    """
    command = f"yoke session-control evidence get --session {session_id}"
    if evidence_id:
        command += f" --evidence-id {evidence_id}"
    return command


def evidence_pull_suffix(session_id: str, evidence_id: str | None = None) -> str:
    """Return the trailing clause a report row appends, or nothing to append.

    A row naming a failure on another machine is exactly where the reader
    needs this, and exactly where they have no way to compose it themselves,
    so the rows share one renderer instead of each building the string.
    """
    if not session_id:
        return ""
    return f"; evidence `{evidence_pull_command(session_id, evidence_id)}`"


class EvidenceFileEntry(BaseModel):
    """One machine-local file the owning relay holds for a session."""

    model_config = ConfigDict(extra="forbid")
    name: str
    kind: EvidenceKind
    size_bytes: int
    modified_at: str


class EvidenceGetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    kind: Optional[EvidenceKind] = None
    #: One `name` from a previous listing. Without it the relay reads the most
    #: recently modified file it holds for the requested kind.
    file: Optional[str] = None
    #: An exact `nd-` native diagnostic reference, as carried by an attempt's
    #: evidence and linked from the fleet report.
    evidence_id: Optional[str] = None
    tail: int = Field(
        default=EVIDENCE_TAIL_DEFAULT_LINES, ge=1, le=EVIDENCE_TAIL_MAX_LINES
    )
    wait_seconds: int = Field(
        default=EVIDENCE_WAIT_DEFAULT_SECONDS, ge=0, le=EVIDENCE_WAIT_MAX_SECONDS
    )


class EvidenceGetResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    fetch_id: str
    session_id: str
    machine_id: str
    state: str
    result_code: Optional[str] = None
    files: List[Dict[str, Any]] = Field(default_factory=list)
    selected_file: Optional[str] = None
    content: Optional[str] = None
    content_bytes: int = 0
    truncated: bool = False
    #: Present while the answer has not arrived: the command that reads it back.
    recovery: Optional[str] = None


__all__ = [
    "EVIDENCE_KINDS",
    "EVIDENCE_LEASE_SECONDS",
    "EVIDENCE_MAX_BYTES",
    "EVIDENCE_REQUEST_TTL_SECONDS",
    "EVIDENCE_RESULT_CODES",
    "EVIDENCE_TAIL_DEFAULT_LINES",
    "EVIDENCE_TAIL_MAX_LINES",
    "EVIDENCE_WAIT_DEFAULT_SECONDS",
    "EVIDENCE_WAIT_MAX_SECONDS",
    "EvidenceFileEntry",
    "EvidenceGetRequest",
    "EvidenceGetResponse",
    "EvidenceKind",
    "evidence_pull_command",
    "evidence_pull_suffix",
    "evidence_result_succeeded",
]
