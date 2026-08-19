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
    """Name the dispatched or covering run immediately before polling it."""
    run_url = html_url or f"https://github.com/{repo}/actions/runs/{run_id}"
    _emit(
        f"requirement={requirement_id} {source} run={run_id} {run_url}",
        stream=stream,
    )
    _emit(
        f"inspect with `gh run view {run_id} --repo {repo}`; watch with "
        f"`gh run watch {run_id} --repo {repo}`",
        stream=stream,
    )
    _emit(
        "if cancellation stalls, force-cancel with "
        f"`gh api --method POST repos/{repo}/actions/runs/{run_id}/"
        f"force-cancel`; after this invocation exits, retry "
        f"`yoke qa case run --requirement-id {requirement_id}`",
        stream=stream,
    )
    return run_url


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
    "relay_poll_output",
]
