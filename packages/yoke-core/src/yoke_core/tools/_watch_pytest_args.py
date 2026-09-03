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
import os
import re
from pathlib import Path
from typing import Sequence

from yoke_core.domain import verification_tree_binding
from yoke_core.tools import _watch_digest, _watch_runner

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


def parse_args(argv: Sequence[str], prog: str) -> argparse.Namespace:
    """Parse wrapper flags; pytest pass-through stays in ``passthrough``."""
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Run pytest under a shared raw+progress watcher wrapper.",
        epilog=(
            "Full-suite shape: pass the three anchors 'runtime/api/ "
            "runtime/harness/ tests/' — never bare 'runtime/', which "
            "demotes runtime/api/conftest.py from initial-conftest status "
            "and fails collection. The wrapper refuses bare 'runtime/'."
        ),
        allow_abbrev=False,
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
        const="main",
        default=None,
        metavar="BASE",
        help="Run only the tests reachable from this branch's changes "
        "(default base: main). Bounded by default: an unbounded change "
        "runs the computable subset and prints an advisory. Pass "
        "--widen for the local full sweep (CI-outage fallback).",
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


# Pytest flags that consume the following token, so a flag value like
# ``-k runtime`` is never mistaken for a positional path arg.
_PYTEST_VALUE_FLAGS = frozenset(
    {"-k", "-m", "-n", "-p", "-o", "-W", "-c", "--rootdir", "--numprocesses"}
)


def has_bare_runtime_path(args: Sequence[str]) -> bool:
    """Return True when a positional pytest path arg is bare ``runtime``.

    Covers the ``runtime``, ``runtime/``, and ``./runtime/`` spellings
    via normpath. Anchored paths (``runtime/api/``) and flag values are
    never matched.
    """
    skip_next = False
    for token in args:
        if skip_next:
            skip_next = False
            continue
        if token.startswith("-"):
            skip_next = token in _PYTEST_VALUE_FLAGS
            continue
        if os.path.normpath(token) == "runtime":
            return True
    return False


def supplied_test_files(args: Sequence[str]) -> tuple[str, ...]:
    """Return explicit ``.py`` collection paths in pass-through *args*.

    Pytest node ids retain their selector suffix for the diagnostic while
    path validation below checks only the file portion before ``::``.
    """
    files: list[str] = []
    skip_next = False
    for token in args:
        if skip_next:
            skip_next = False
            continue
        if token == "--":
            continue
        if token.startswith("-"):
            skip_next = token in _PYTEST_VALUE_FLAGS
            continue
        if token.partition("::")[0].endswith(".py") and token not in files:
            files.append(token)
    return tuple(files)


def _missing_test_files(args: Sequence[str], cwd: Path) -> tuple[str, ...]:
    return tuple(
        token
        for token in supplied_test_files(args)
        if not (cwd / token.partition("::")[0]).is_file()
    )


def invalid_test_selection_diagnostic(args: Sequence[str], cwd: Path) -> str | None:
    """Explain a mixed explicit-file selection containing missing paths."""
    files = supplied_test_files(args)
    missing = set(_missing_test_files(args, cwd))
    if not missing:
        return None
    lines = [
        "watch_pytest invalid selection: "
        f"{len(files)} supplied test file(s), {len(missing)} missing; "
        "pytest was not started."
    ]
    for token in files:
        reason = (
            "path does not exist"
            if token in missing
            else "exists; not run because the combined selection is invalid"
        )
        lines.append(f"watch_pytest selection: {token} — {reason}")
    return "\n".join(lines)


def _active_selection_filters(args: Sequence[str]) -> tuple[str, ...]:
    filters: list[str] = []
    for index, token in enumerate(args):
        if token in {"-k", "-m"} and index + 1 < len(args):
            filters.append(f"{token} {args[index + 1]}")
        elif token.startswith(("-k", "-m")) and not token.startswith("--"):
            filters.append(token)
    return tuple(filters)


def zero_collection_diagnostic(
    args: Sequence[str], collected_items: int | None, cwd: Path
) -> str | None:
    """Explain an all-existing explicit selection that yielded no items."""
    files = supplied_test_files(args)
    if collected_items != 0 or not files:
        return None
    missing = set(_missing_test_files(args, cwd))
    filters = _active_selection_filters(args)
    lines = [
        f"# watch_pytest zero-collection selection: {len(files)} supplied test file(s)"
    ]
    for token in files:
        if token in missing:
            reason = "path does not exist"
        elif missing:
            reason = "not collected after pytest received a missing path"
        elif filters:
            reason = "no item matched active filter(s): " + ", ".join(filters)
        else:
            reason = "pytest reported no collectable items in this selection"
        lines.append(f"# watch_pytest no-items: {token} — {reason}")
    return "\n".join(lines)


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
