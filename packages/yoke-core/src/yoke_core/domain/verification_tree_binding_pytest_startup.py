"""Host the verification tree binding at the layer pytest itself starts.

A guard installed at a runner's *entry* covers exactly the entries it was
installed in. The watcher wrapper, the generic runner, and the QA case
executor each judge the tree before starting pytest — but a raw
``python3 -m pytest``, an IDE run button, and any entry point added later
walk straight past all three, and a run rooted in a checkout the session
does not hold reports a green for code nobody changed.

:func:`pytest_startup_verdict` is the same decision
(:mod:`yoke_core.domain.verification_tree_binding` owns it) called from
the repo root ``conftest.py``. That conftest belongs to the tree being
collected, so it is reached no matter what shape the invocation took, and
no future entry point has to remember to opt in.

The cost of standing there is the reason for the marker: this runs on
every pytest start, including once per xdist worker. An entry point that
has already judged its tree hands the child :func:`with_binding_evaluated`,
so the startup check passes through without a second control-plane
lookup, and a clean verdict marks the environment the workers inherit.
"""

from __future__ import annotations

import os
import sys
from typing import Mapping, MutableMapping, Optional, Sequence

from yoke_core.domain.verification_tree_binding import (
    ALLOW_TREE_MISMATCH_FLAG,
    TreeBindingVerdict,
    evaluate_run,
)

#: Exit status for a run refused before pytest started. One value across
#: every pytest entry surface so a caller branches on one number.
TREE_BINDING_REFUSED_EXIT_STATUS = 3

#: Set by an entry point that already judged the tree it is about to run
#: in, so the child process's startup check inherits that answer instead
#: of paying a second control-plane lookup.
BINDING_EVALUATED_ENV = "YOKE_TREE_BINDING_EVALUATED"

#: Surface name carried by this check's refusal and notice.
PYTEST_STARTUP_SURFACE = "pytest"


def with_binding_evaluated(env: Mapping[str, str]) -> dict[str, str]:
    """A copy of *env* marked as already judged by this entry point.

    Hand this to a child that will start pytest. The startup check reads
    the marker and passes through, so an entry point that has done the
    lookup does not pay for it again — nor does each xdist worker the
    run spawns.
    """
    marked = dict(env)
    marked[BINDING_EVALUATED_ENV] = "1"
    return marked


def pytest_startup_verdict(
    tree: str,
    *,
    argv: Optional[Sequence[str]] = None,
    env: Optional[MutableMapping[str, str]] = None,
) -> TreeBindingVerdict:
    """Judge *tree* at pytest startup, from the repo root conftest.

    *tree* is the collected checkout's own root — not the working
    directory — so a run launched from the claimed lane against another
    checkout's tests is judged on the tree it actually collects.

    The override arrives as
    :data:`~yoke_core.domain.verification_tree_binding.ALLOW_TREE_MISMATCH_FLAG`
    in the pytest argv, matching the flag every other entry point
    accepts. A verdict that lets the run proceed marks *env*, so the
    workers and any nested pytest inherit this answer rather than
    repeating the lookup.
    """
    environ = os.environ if env is None else env
    if environ.get(BINDING_EVALUATED_ENV):
        return TreeBindingVerdict()
    arguments = list(sys.argv if argv is None else argv)
    verdict = evaluate_run(
        surface=PYTEST_STARTUP_SURFACE,
        tree=tree,
        allow_mismatch=ALLOW_TREE_MISMATCH_FLAG in arguments,
    )
    if verdict.refusal is None:
        environ[BINDING_EVALUATED_ENV] = "1"
    return verdict


__all__ = [
    "BINDING_EVALUATED_ENV",
    "PYTEST_STARTUP_SURFACE",
    "TREE_BINDING_REFUSED_EXIT_STATUS",
    "pytest_startup_verdict",
    "with_binding_evaluated",
]
