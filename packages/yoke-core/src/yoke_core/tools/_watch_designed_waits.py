"""Non-zero watcher exits the watched command chose, and how to continue them.

A watcher renders every non-zero child exit as a failure. The deploy
pipeline's scoped-QA hold is not one: it parks the run at a QA stage the
run may not pass on its own, which is the designed outcome of a flow that
carries QA. Rendering it as a failure told the operator "terminal cause
not diagnosed from captured output; inspect the raw capture before
retrying" — an instruction to investigate a healthy wait, with no way to
continue it, on the one exit that most needs its continuation named.

The wait's own report is the authority for what it says. The pipeline
prints the prefix naming the hold and knows the recovery for it, so this
reads that prefix back and asks the recovery's owner to render the
continuation rather than re-deriving either.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


#: The ``yoke watch deploy`` wrapper's kind token, owned here because the
#: designed-wait table is keyed by it and the wrapper imports this module.
DEPLOY_WATCH_KIND = "deploy"

#: Both scoped-QA hold reports end by naming the run they are holding, and
#: both count the obligations that hold it. The recovery is a function of
#: exactly those two facts.
_HOLD_RUN_RE = re.compile(r"for run (\S+?)\.?\s*$")
_HOLD_COUNT_RE = re.compile(r"(\d+) blocking QA")


@dataclass(frozen=True)
class DesignedWait:
    """A non-zero exit that is a wait, with the command that continues it."""

    cause: str
    continuation: str


def _compact(line: str) -> str:
    return " ".join(line.split())


def _scoped_qa_hold(raw_capture: Path) -> DesignedWait | None:
    """The run's scoped-QA hold report, when the capture carries one."""
    from yoke_core.domain.deployment_run_completion_preconditions import (
        AWAITING_QA_PREFIX,
        HELD_STAGE_PREFIX,
        redrive_recovery,
    )

    prefixes = (AWAITING_QA_PREFIX, HELD_STAGE_PREFIX)
    cause: str | None = None
    with raw_capture.open(encoding="utf-8", errors="replace") as capture:
        for line in capture:
            text = _compact(line)
            if text.startswith(prefixes):
                cause = text
    if cause is None:
        return None
    run = _HOLD_RUN_RE.search(cause)
    count = _HOLD_COUNT_RE.search(cause)
    if run is None or count is None:
        return None
    return DesignedWait(
        cause=cause,
        continuation=redrive_recovery(run.group(1), unresolved=int(count.group(1))),
    )


def designed_wait(
    *, kind: str, exit_code: int, raw_capture: Path
) -> DesignedWait | None:
    """The wait a non-zero *exit_code* names, or ``None`` for a failure.

    A refusal that shares the exit code is not a wait: detection requires
    the hold's own report in the capture, so a resume the pipeline refused
    for trying to skip QA still renders as the failure it is.
    """
    from yoke_core.domain.deploy_pipeline import EXIT_AWAITING_QA

    if kind != DEPLOY_WATCH_KIND or exit_code != EXIT_AWAITING_QA:
        return None
    return _scoped_qa_hold(raw_capture)


__all__ = ["DEPLOY_WATCH_KIND", "DesignedWait", "designed_wait"]
