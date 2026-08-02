"""Who owns a contested anchor pid — and when contention heals.

A registry record binds one anchor pid to one session. When a write arrives
carrying a *different* session id for the same live process, the pid looks
shared and the registry must refuse to identify anyone — but refusal has to
be a state the registry can leave, not a latch. This module decides tenancy
on every write:

- The **writer always remains a candidate**: its hook event is live proof of
  the process, even while its session row is transiently ended.
- A **recorded contender is dropped** once the sessions table positively says
  it ended (``contender_is_live`` returning ``False``), or once a *clean*
  registry record anchors it to a different live process — a session has one
  per-conversation process, so a live home elsewhere means its claim on this
  pid was written by someone else's descendant.
- Anything unknown (probe unavailable, probe error, unregistered id) is kept,
  so ambiguity still fails closed toward "shared".

One live candidate means the anchor is that session's again; two or more
mean the record stays a contention marker — now carrying the contending ids
and a writer breadcrumb, so the next occurrence is attributable instead of
being a blank.

Pure standard library, like the rest of the identity contract.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

# True = the session is live (active or merely stale); False = its row is
# positively ended; None = unknown (no row yet, probe unavailable, error).
ContenderIsLive = Callable[[str], Optional[bool]]

_BREADCRUMB_ARGV_PARTS = 4
_BREADCRUMB_MAX_CHARS = 160


@dataclass(frozen=True)
class TenancyDecision:
    """The registry write resolved from one anchor-write attempt."""

    tenant_session_id: str
    contended: bool
    contending_session_ids: tuple[str, ...] = ()


def _candidate_ids(
    existing: Optional[Dict[str, Any]], session_id: str,
) -> set[str]:
    candidates = {session_id}
    if not existing:
        return candidates
    recorded = existing.get("session_id")
    if isinstance(recorded, str) and recorded:
        candidates.add(recorded)
    listed = existing.get("contending_session_ids")
    if isinstance(listed, (list, tuple)):
        candidates.update(
            str(value) for value in listed if isinstance(value, str) and value
        )
    return candidates


def _anchored_live_elsewhere(
    candidate: str,
    *,
    anchors_dir: Optional[Path],
    this_pid: int,
    load_record: Callable[[Path], Optional[Dict[str, Any]]],
    start_time_of: Callable[[int], Optional[str]],
) -> bool:
    """Whether a *clean* record on another live process claims ``candidate``.

    Only clean records count: a contention marker elsewhere is itself an
    ambiguity, not evidence of where the session really lives.
    """
    if anchors_dir is None:
        return False
    try:
        for path in anchors_dir.glob("*.json"):
            try:
                pid = int(path.stem)
            except ValueError:
                continue
            if pid == this_pid:
                continue
            record = load_record(path)
            if not record or record.get("shared_by_multiple_sessions"):
                continue
            if record.get("session_id") != candidate:
                continue
            recorded_start = record.get("anchor_start_time")
            if recorded_start and start_time_of(pid) == recorded_start:
                return True
    except Exception:  # noqa: BLE001 — a scan failure is "no evidence"
        return False
    return False


def resolve_tenancy(
    existing: Optional[Dict[str, Any]],
    session_id: str,
    *,
    anchors_dir: Optional[Path],
    this_pid: int,
    load_record: Callable[[Path], Optional[Dict[str, Any]]],
    start_time_of: Callable[[int], Optional[str]],
    contender_is_live: Optional[ContenderIsLive] = None,
) -> TenancyDecision:
    """Decide who the anchor belongs to after this write.

    ``existing`` is the current record for the same live process (the caller
    has already matched start times); ``session_id`` is the writer's.
    """
    candidates = _candidate_ids(existing, session_id)
    if len(candidates) == 1:
        return TenancyDecision(tenant_session_id=session_id, contended=False)

    kept = {session_id}
    for candidate in candidates - {session_id}:
        if contender_is_live is not None:
            try:
                if contender_is_live(candidate) is False:
                    continue
            except Exception:  # noqa: BLE001 — unknown keeps the candidate
                pass
        if _anchored_live_elsewhere(
            candidate,
            anchors_dir=anchors_dir,
            this_pid=this_pid,
            load_record=load_record,
            start_time_of=start_time_of,
        ):
            continue
        kept.add(candidate)

    if len(kept) == 1:
        return TenancyDecision(tenant_session_id=session_id, contended=False)
    return TenancyDecision(
        tenant_session_id="",
        contended=True,
        contending_session_ids=tuple(sorted(kept)),
    )


def writer_breadcrumb(argv: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """Who wrote a contended record — enough to attribute a recurrence."""
    source = list(sys.argv if argv is None else argv)
    joined = " ".join(source[:_BREADCRUMB_ARGV_PARTS])
    return {
        "last_writer_pid": os.getpid(),
        "last_writer_argv": joined[:_BREADCRUMB_MAX_CHARS],
    }


__all__ = [
    "ContenderIsLive",
    "TenancyDecision",
    "resolve_tenancy",
    "writer_breadcrumb",
]
