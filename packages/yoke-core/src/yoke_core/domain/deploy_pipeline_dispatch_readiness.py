"""Wait for a GitHub workflow dispatch's preconditions together.

A release workflow dispatch waits on two independent facts about one release
commit: CI passing on it, and whatever must be prepared for it before it
ships — the fleet rehearsal receipts. Both are knowable from the moment the
release commit is, and neither reads the other, so waiting for one and then
starting the other only adds the first wait to the second. The CI gate polls
GitHub from a worker thread while the preparation runs on this one. The
preparation stays here because the rehearsal watcher installs the signal
handlers that reap its child process group, which only the main thread can.

Dispatch proceeds only when both pass. When both refuse, the CI gate's
refusal is reported, since a release CI did not pass is not a release whose
rehearsal matters.
"""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from typing import Callable, Mapping, Optional, Tuple

CiGate = Callable[[], Tuple[bool, str]]
#: Called with the commit the run holds for each bound input.
Preparation = Callable[[Mapping[str, str]], Tuple[int, str]]


def await_dispatch_readiness(
    ci_gate: Optional[CiGate],
    before_dispatch: Optional[Preparation],
    bound_inputs: Optional[Mapping[str, str]] = None,
) -> tuple[int, str]:
    """Run ``before_dispatch`` while ``ci_gate`` waits; refuse unless both pass.

    ``ci_gate`` is ``None`` when the stage skips the CI gate, and
    ``before_dispatch`` is ``None`` when nothing has to be prepared.
    """
    bound = dict(bound_inputs or {})
    if ci_gate is None:
        print("  CI gate: skipped by this deployment-flow stage")
        return _prepare(before_dispatch, bound)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="ci-gate") as pool:
        waiting = pool.submit(copy_context().run, ci_gate)
        prepared_rc, prepared_diagnostic = _prepare(before_dispatch, bound)
        ci_passed, ci_msg = waiting.result()
    if ci_msg:
        print(ci_msg, file=sys.stderr if not ci_passed else sys.stdout)
    if not ci_passed:
        return 1, ci_msg or ""
    return prepared_rc, prepared_diagnostic


def _prepare(
    before_dispatch: Optional[Preparation], bound: Mapping[str, str]
) -> tuple[int, str]:
    if before_dispatch is None:
        return 0, ""
    return before_dispatch(bound)


__all__ = ["await_dispatch_readiness"]
