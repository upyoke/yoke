"""Per-check progress lines for a doctor run, shared by every runner.

Doctor's long runs are followed through a line filter (see
:mod:`yoke_core.tools.watch_doctor`), which recognises exactly two
shapes: ``running HC-<slug>`` when a check starts and
``HC-<slug>: PASS|WARN|FAIL|SKIP`` when it finishes. Rendering those
here means the engine entrypoint, the ``doctor.run.run`` handler, and
the relayed client all speak the same two shapes instead of each
authoring its own.

Emission is opt-in. A run installs a sink with :func:`progress_to`;
without one every emitter is a no-op. That is what keeps the handler
silent when it executes server-side for a relayed call — the server has
no operator watching its stdout — while the same handler streams when a
local-Postgres connection dispatches it in-process, in the caller's own
process, under the caller's sink.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Iterable, Iterator, Mapping, Optional, TextIO

from yoke_core.engines.doctor_applicability import NOT_APPLICABLE

#: Receives one already-rendered progress line, without its newline.
ProgressWriter = Callable[[str], None]

_SINK: ContextVar[Optional[ProgressWriter]] = ContextVar(
    "doctor_progress_sink", default=None
)
_WITHHOLD_VERDICTS: ContextVar[bool] = ContextVar(
    "doctor_progress_withhold_verdicts", default=False
)


def check_started_line(slug: str) -> str:
    """The line announcing that HC *slug* is about to run."""
    return f"running HC-{slug}"


def check_result_line(check_id: str, result: str) -> str:
    """The line announcing one recorded verdict."""
    return f"{check_id}: {result}"


@contextmanager
def progress_to(stream: TextIO) -> Iterator[None]:
    """Stream this context's doctor progress lines to *stream*.

    Flushed per line: a watcher following the stream is the reason the
    lines exist, and a buffered progress line is not progress.
    """

    def write(line: str) -> None:
        stream.write(f"{line}\n")
        stream.flush()

    token = _SINK.set(write)
    try:
        yield
    finally:
        _SINK.reset(token)


def emit(line: str) -> None:
    """Send one rendered line to the installed sink, if any."""
    sink = _SINK.get()
    if sink is not None:
        sink(line)


def check_started(slug: str) -> None:
    emit(check_started_line(slug))


def check_finished(check_id: str, result: str) -> None:
    if _WITHHOLD_VERDICTS.get():
        return
    emit(check_result_line(check_id, result))


@contextmanager
def verdicts_withheld() -> Iterator[None]:
    """Hold back verdicts inside this block; the caller emits the final ones.

    A runner that executes a check without the authority the check needs
    rewrites the resulting failure as not-applicable once the call
    returns (:func:`doctor_https_compose.note_missing_control_plane`).
    Letting the raw failure out first wakes a follower urgently for a
    verdict the report will never carry: one relayed ``--quick`` run
    emitted eleven such lines against a single real failure. Start lines
    still stream, so a long batch stays visibly alive, and the caller
    emits each verdict once it is final — a genuine failure still reaches
    the urgent tier, and a rewritten one goes out as the N/A it became.
    """
    token = _WITHHOLD_VERDICTS.set(True)
    try:
        yield
    finally:
        _WITHHOLD_VERDICTS.reset(token)


def emit_result_rows(rows: Iterable[Mapping[str, object]]) -> None:
    """Emit verdict lines for result rows that arrived from elsewhere.

    A relayed run has no local check loop to hook, so its client emits
    from the rows each bounded batch returns. Not-applicable rows are
    skipped for parity with the in-process loops, which announce only
    the checks they actually execute; a run's N/A set is reported in the
    report's own section.
    """
    for row in rows:
        severity = str(row.get("severity") or "")
        if not severity or severity == NOT_APPLICABLE:
            continue
        check_finished(str(row.get("hc") or ""), severity)


__all__ = [
    "ProgressWriter",
    "check_finished",
    "check_result_line",
    "check_started",
    "check_started_line",
    "emit",
    "emit_result_rows",
    "progress_to",
    "verdicts_withheld",
]
