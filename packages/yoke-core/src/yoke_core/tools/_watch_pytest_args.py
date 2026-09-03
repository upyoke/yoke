"""Pass-through arg-shape guards and wrapper flags for ``watch_pytest``.

Split out of :mod:`yoke_core.tools.watch_pytest` to keep that module
under the authored-file line cap. Owns the rejection guards that repair
a doomed invocation before the underlying pytest run launches: the
nested ``python3 -m pytest`` shape and the bare ``runtime/`` path shape
(which demotes ``runtime/api/conftest.py`` from initial-conftest status
and fails collection — ``pytest_plugins`` in a non-top-level conftest).
Also owns wrapper-flag parsing so ``--impacted`` stays bounded by default.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Sequence

from yoke_core.domain import verification_tree_binding
from yoke_core.tools import _watch_digest, _watch_runner
from yoke_core.tools._impacted_changed_paths import DEFAULT_BASE_REF
from yoke_core.tools._watch_pytest_selection_diagnostics import (  # noqa: F401
    has_bare_runtime_path,
    invalid_test_selection_diagnostic,
    pytest_flag_consumes_value,
    supplied_test_files,
    zero_collection_diagnostic,
)
from yoke_core.tools.pytest_remote_selection import LOCAL_ENV, LOCAL_FLAG

NESTED_PYTEST_REJECTION_MESSAGE = (
    "watch_pytest expects bare pytest args after --; "
    "do not include python3 -m pytest.\n"
    "Example: python3 -m yoke_core.tools.watch_pytest -- runtime/api/ -q"
)

BARE_RUNTIME_REJECTION_MESSAGE = (
    "watch_pytest refuses bare 'runtime/' as a pytest path: anchoring "
    "collection at runtime/ demotes runtime/api/conftest.py from "
    'initial-conftest status and collection fails with "Defining '
    "'pytest_plugins' in a non-top-level conftest is no longer "
    'supported".\n'
    "Full-suite shape: python3 -m yoke_core.tools.watch_pytest -- "
    "runtime/api/ runtime/harness/ tests/"
)

PYTEST_USAGE_ERROR_EXIT_STATUS = 4
#: Canonical agent-facing form, used where a message repairs a command.
WATCH_PYTEST_COMMAND = "yoke watch pytest"
BOUNDED_FLAG = "--bounded"
WIDEN_FLAG = "--widen"
BOUNDED_WITHOUT_IMPACTED = "watch_pytest: --bounded only applies with --impacted"
WIDEN_WITHOUT_IMPACTED = "watch_pytest: --widen only applies with --impacted"
#: Closing line for a selection that resolved to no test files at all.
#: A follower reads it as the whole run: nothing was executed, and the
#: reason lines sit above it in this same capture.
NO_SELECTED_TESTS = (
    "watch_pytest: the impacted selection chose no test files; nothing was run."
)
WOULD_WIDEN_ADVISORY = (
    "watch_pytest: selection would widen (rule={rule}, triggers={triggers}) "
    "— the final QA case run covers the rest"
)


def format_would_widen_advisory(*, rule: str, trigger_paths: Sequence[str]) -> str:
    """One-line advisory when ``--impacted`` declines a full-sweep widen."""
    return WOULD_WIDEN_ADVISORY.format(
        rule=rule or "none",
        triggers=",".join(trigger_paths) or "none",
    )


def extract_wrapper_flag(argv: Sequence[str], flag: str) -> tuple[list[str], bool]:
    """Pull a bare wrapper *flag* out of any position in ``argv``.

    ``passthrough`` uses ``nargs=argparse.REMAINDER``, which means the
    flag would otherwise reach pytest verbatim if placed after the
    ``--`` separator. Pre-extracting makes every position equivalent.
    """
    filtered: list[str] = []
    found = False
    for arg in argv:
        if arg == flag:
            found = True
            continue
        filtered.append(arg)
    return filtered, found


def parse_args(argv: Sequence[str], prog: str) -> argparse.Namespace:
    """Parse wrapper flags; pytest pass-through stays in ``passthrough``."""
    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            "Run pytest under a shared raw+progress watcher wrapper. For a "
            "project that declares its CI workflow the run executes on CI: "
            "the lane commit is pushed, the selection workflow is dispatched "
            "with (base_sha, head_sha), and the exit status mirrors the run's "
            f"conclusion. {LOCAL_FLAG} runs on this machine instead, under "
            "the machine-wide worker budget."
        ),
        epilog=(
            "Full-suite shape: pass the three anchors 'runtime/api/ "
            "runtime/harness/ tests/' — never bare 'runtime/', which "
            "demotes runtime/api/conftest.py from initial-conftest status "
            "and fails collection. The wrapper refuses bare 'runtime/'. "
            "A remote run refuses an uncommitted tree (commit, then run) "
            "and a checkout on the base branch; it drops -n/--numprocesses "
            "and --rootdir, which describe this machine. Exit statuses: "
            "pytest's own locally; remotely 0 success, 1 failure, 2 refused "
            "before dispatch, 3 timed out, 4 CI unreachable or dispatch "
            "refused, 5 cancelled."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        LOCAL_FLAG,
        dest="local",
        action="store_true",
        help="Run on this machine instead of the project's CI: order-"
        "sensitive debugging (-n 0), a tree you want to try before "
        "committing, or an unreachable CI. Local runs take their xdist "
        f"workers from one machine-wide budget. {LOCAL_ENV}=1 does the "
        "same for a whole shell.",
    )
    parser.add_argument(
        _watch_runner.PRINT_STREAMING_PAIR_FLAG,
        dest="print_streaming_pair",
        action="store_true",
        help="Print a ready-to-paste background command + progress-tail pair "
        "and exit. Mints fresh capture paths.",
    )
    _watch_digest.attach_flush_seconds(parser)
    parser.add_argument(
        "--raw-capture",
        type=Path,
        default=None,
        help="Explicit raw capture file path. Defaults to a helper-resolved "
        "path under the project scratch root. Must precede the '--' "
        "separator; after it, pytest takes the flag as an unknown option.",
    )
    parser.add_argument(
        "--progress-capture",
        type=Path,
        default=None,
        help="Explicit progress capture file path, the one watch_tail "
        "follows. Defaults to a helper-resolved path under the project "
        "scratch root. Must precede the '--' separator; after it, pytest "
        "takes the flag as an unknown option.",
    )
    parser.add_argument(
        "--impacted",
        nargs="?",
        const=DEFAULT_BASE_REF,
        default=None,
        metavar="BASE",
        help="Run only the tests reachable from this branch's changes "
        f"(default base: {DEFAULT_BASE_REF}). Bounded by default: an "
        "unbounded change runs the computable subset and prints an "
        "advisory. Pass --widen for the local full sweep (CI-outage "
        "fallback).",
    )
    parser.add_argument(
        BOUNDED_FLAG,
        dest="bounded",
        action="store_true",
        help="Accepted no-op; --impacted is already bounded by default.",
    )
    parser.add_argument(
        WIDEN_FLAG,
        dest="widen",
        action="store_true",
        help="With --impacted, take the local full sweep instead of the "
        "bounded subset (CI-outage fallback only).",
    )
    parser.add_argument(
        verification_tree_binding.ALLOW_TREE_MISMATCH_FLAG,
        dest="allow_tree_mismatch",
        action="store_true",
        help="Run even when this tree is outside the session's claimed "
        "worktree. For a deliberate cross-tree run; the wrapper names both "
        "trees so the green is attributable.",
    )
    parser.add_argument(
        "passthrough",
        nargs=argparse.REMAINDER,
        help=(
            "Bare pytest arguments. Use ``--`` to separate wrapper flags "
            "from pytest flags when ambiguous. Do NOT include "
            "``python3 -m pytest``; the wrapper supplies that prefix."
        ),
    )
    return parser.parse_args(list(argv))


# Match the bare interpreter names operators most commonly retype, plus
# the literal ``sys.executable`` token (sometimes copied from the wrapper
# source). Path forms (``/usr/bin/python3``) reuse this against the
# basename so we accept them without separately enumerating prefixes.
_PYTHON_BASENAME_RE = re.compile(r"^python(\d+(\.\d+)?)?$")


def looks_like_python_executable(token: str) -> bool:
    """Return True when ``token`` names a Python interpreter.

    Accepts ``python``, ``python3``, ``python3.11`` (and similar
    versioned forms), any path ending in one of those names, and the
    literal string ``sys.executable``. The literal token is included
    because the wrapper source itself spells the underlying invocation
    that way and operators occasionally paste it verbatim.
    """
    if token == "sys.executable":
        return True
    base = token.rsplit("/", 1)[-1]
    return bool(_PYTHON_BASENAME_RE.match(base))


def is_nested_pytest_invocation(args: Sequence[str]) -> bool:
    """Return True if pass-through ``args`` start with ``<python> -m pytest``."""
    if len(args) < 3:
        return False
    return (
        looks_like_python_executable(args[0])
        and args[1] == "-m"
        and args[2] == "pytest"
    )


def argument_shape_refusal(args: Sequence[str], cwd: Path) -> tuple[str, int] | None:
    """The first refusal the pass-through earns, with its exit status.

    One gate for every way a pass-through is wrong before pytest starts,
    so the wrapper has a single place to close its claimed capture.
    """
    misplaced = _watch_runner.misplaced_capture_flags(args)
    if misplaced:
        message = _watch_runner.misplaced_capture_rejection(
            misplaced, command=WATCH_PYTEST_COMMAND
        )
        return message, PYTEST_USAGE_ERROR_EXIT_STATUS
    if is_nested_pytest_invocation(args):
        return NESTED_PYTEST_REJECTION_MESSAGE, 2
    if has_bare_runtime_path(args):
        return BARE_RUNTIME_REJECTION_MESSAGE, 2
    invalid = invalid_test_selection_diagnostic(args, cwd)
    if invalid is not None:
        return invalid, PYTEST_USAGE_ERROR_EXIT_STATUS
    return None
