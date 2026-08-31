"""Live stderr progress for a Command-method QA case running on CI."""

from __future__ import annotations

import contextlib
import sys
from collections.abc import Iterator
from typing import TextIO

PROGRESS_PREFIX = "# qa case run:"


class _FlushingWriter:
    """Forward writes and flush immediately so a polling line is observable."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def write(self, text: str) -> int:
        written = self._stream.write(text)
        self._stream.flush()
        return written

    def flush(self) -> None:
        self._stream.flush()


def _emit(message: str, *, stream: TextIO | None = None) -> None:
    print(
        f"{PROGRESS_PREFIX} {message}",
        file=sys.stderr if stream is None else stream,
        flush=True,
    )


def announce_dispatch(
    requirement_id: int,
    *,
    repo: str,
    workflow: str,
    branch: str,
    stream: TextIO | None = None,
) -> None:
    """Name a dispatch before its GitHub run id is available."""
    _emit(
        f"requirement={requirement_id} dispatching {workflow} on "
        f"{repo}@{branch}; no run id yet",
        stream=stream,
    )


def announce_covering_wait(
    requirement_id: int,
    *,
    repo: str,
    head_sha: str,
    next_poll_seconds: float,
    stream: TextIO | None = None,
) -> None:
    """Name one wait for GitHub to mint a pull-request run."""
    _emit(
        f"requirement={requirement_id} waiting for a covering run on "
        f"{repo}@{head_sha[:12]}; no run id yet; "
        f"next poll={next_poll_seconds:g}s",
        stream=stream,
    )


def announce_run(
    requirement_id: int,
    *,
    repo: str,
    run_id: str,
    html_url: str = "",
    source: str,
    stream: TextIO | None = None,
) -> str:
    """Name the run this case is about, and how it came to be the one.

    ``source`` is one of
    :mod:`yoke_core.domain.qa_case_ci_covering_run`'s values, so the
    stderr stream and the recorded evidence agree about whether this
    invocation dispatched the run, attached to one already in flight, or
    adopted one that had already concluded.
    """
    run_url = html_url or f"https://github.com/{repo}/actions/runs/{run_id}"
    _emit(
        f"requirement={requirement_id} {source} run={run_id} {run_url}",
        stream=stream,
    )
    _emit(
        f"inspect failures with "
        f"`yoke github-actions failed-log {repo} {run_id} --project <project>`; "
        f"watch with "
        f"`gh run watch {run_id} --repo {repo}`",
        stream=stream,
    )
    _emit(
        "if cancellation stalls, force-cancel with "
        f"`gh api --method POST repos/{repo}/actions/runs/{run_id}/"
        f"force-cancel`. If this invocation is interrupted before the run "
        f"concludes, re-run `yoke qa case run --requirement-id "
        f"{requirement_id}` on the same commit: the run above is adopted "
        "or rejoined rather than re-executed",
        stream=stream,
    )
    return run_url


def announce_superseded_run_cancelled(
    *,
    repo: str,
    branch: str,
    run_id: str,
    stream: TextIO | None = None,
) -> None:
    """Record the older pull-request run the rebased gate force-cancelled."""
    _emit(
        f"force-cancelled superseded run={run_id} repo={repo} branch={branch}",
        stream=stream,
    )


@contextlib.contextmanager
def relay_poll_output(stream: TextIO | None = None) -> Iterator[None]:
    """Relay legacy poll narration to flushed stderr for the QA JSON CLI."""
    target = sys.stderr if stream is None else stream
    with contextlib.redirect_stdout(_FlushingWriter(target)):
        yield


__all__ = [
    "PROGRESS_PREFIX",
    "announce_covering_wait",
    "announce_dispatch",
    "announce_run",
    "announce_superseded_run_cancelled",
    "relay_poll_output",
]
