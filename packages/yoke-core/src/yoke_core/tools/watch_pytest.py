"""Command-shaped watcher for pytest runs.

Owns the pytest line classifier so callers do not author a Monitor
filter per invocation — the tail of a raw command line through
``tail -f ... | grep --line-buffered "%\\] "`` is exactly the trap this
wrapper exists to prevent.

The classifier maps:

- ``[ N%]`` per-file progress markers → ``PROGRESS`` with the percent as
  the throttling axis.
- ``FAILED `` and ``ERROR `` per-test summary lines, collection/usage
  errors (``ERROR: file or directory not found:``, ``ERROR: usage:``,
  ``<prog>: error: …``, ``INTERNALERROR>``, the non-top-level conftest
  ``pytest_plugins`` error) → ``URGENT``.
- ``=+ ... (passed|failed|error|ERRORS|no tests ran)`` banners and the
  quiet-mode verdict lines → ``SUMMARY``.
- ``collected N items`` / xdist ``N workers [M items]`` collection
  notices → ``SUMMARY``.

Every other line is ``NOISE`` (raw capture only).

Usage::

    # Direct execution (Codex / shell): streams filtered progress to stdout
    # while preserving full output in the raw capture. Pass BARE pytest
    # args after ``--``; the wrapper supplies the ``python3 -m pytest``
    # prefix itself.
    python3 -m yoke_core.tools.watch_pytest -- runtime/api/

    # Full backend suite — pass the two anchors, never bare ``runtime/``
    # (which demotes runtime/api/conftest.py from initial-conftest status
    # and fails collection; the wrapper refuses it):
    python3 -m yoke_core.tools.watch_pytest -- runtime/api/ runtime/harness/

    # Print the ready-to-paste streaming pair:
    python3 -m yoke_core.tools.watch_pytest --print-streaming-pair -- runtime/api/

    # Serial mode (debug order-sensitive failures):
    python3 -m yoke_core.tools.watch_pytest -- --no-parallel runtime/api/

Parallel-by-default: ``-n auto`` (pytest-xdist) is injected unless the
caller passes ``--no-parallel`` or its own ``-n``/``--numprocesses`` in
the pass-through. The wrapper preserves the underlying ``pytest`` exit
code so callers can still branch on success/failure.

Do NOT pass a full pytest command-shape after ``--``. The wrapper rejects
``-- python3 -m pytest …`` variants before invoking the underlying runner.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Sequence

from yoke_core.tools import (
    _source_pythonpath,
    _watch_pytest_args,
    _watch_pytest_rootdir,
    _watch_runner,
    _watch_worktree_binding,
)
from yoke_core.tools._pytest_parallel import (
    apply_postgres_xdist_auto_env,
    apply_parallel_default,
    split_no_parallel,
)
from yoke_core.tools._watch_throttle import Classification, LineClass

WRAPPER_MODULE = "yoke_core.tools.watch_pytest"
KIND = "pytest"

# Per-class regexes. Each is line-oriented; callers feed one line at a
# time. Keeping them as separate constants lets tests exercise each
# class independently without re-parsing the union pattern.
PYTEST_PROGRESS_RE = re.compile(r"\[\s*(\d+)%\]")
# Per-test summary lines (``FAILED path::test``, ``ERROR path``) plus the
# collection/usage error shapes a watcher must relay so callers do not
# need the raw capture to diagnose a bad invocation: ``ERROR: file or
# directory not found:`` / ``ERROR: usage:`` (UsageError lead lines),
# ``<prog>: error: …`` (argparse detail — the prog token may contain
# spaces, e.g. ``python3 -m pytest: error: …``), xdist ``INTERNALERROR>``
# crash frames, and the non-top-level conftest ``pytest_plugins`` error
# (which xdist surfaces inside ERRORS-section blocks without a prefix).
PYTEST_URGENT_RE = re.compile(
    r"^(?:FAILED|ERROR)[ :]"
    r"|^INTERNALERROR"
    r"|^\S.*?: error: "
    r"|Defining 'pytest_plugins' in a non-top-level conftest"
)
# Closing summary banner. Matches pytest's default-verbose banner
# (``====== 4 passed in 0.42s ======``, ``==== ERRORS ====``,
# ``==== no tests ran in 0.01s ====``) AND pytest's ``-q`` quiet-mode
# verdict lines (``4 passed in 0.42s``, ``no tests ran in 0.01s`` — no
# leading ``=``). The count-led quiet shape requires count + verdict
# word + (`,` or ` in `) so noise lines starting with a digit do not
# accidentally match.
PYTEST_SUMMARY_BANNER_RE = re.compile(
    r"^=+ .*(passed|failed|error|ERRORS|no tests ran)"
    r"|"
    r"^\d+ (passed|failed|error|skipped|xfailed|xpassed|deselected)(,| in )"
    r"|"
    r"^no tests ran in "
)
# Initial collection notice: plain ``collected N items`` plus the xdist
# form ``N workers [M items]`` (the only collection signal xdist prints).
PYTEST_COLLECTED_RE = re.compile(
    r"^collected \d+|^\d+ workers \[\d+ items?\]"
)

# Public union pattern: kept for callers/tests that want a single
# "is this a signal line?" check. Composed from the per-class regexes
# above so there is exactly one source of truth for each shape.
PYTEST_PROGRESS_PATTERN = re.compile(
    r"|".join(
        (
            PYTEST_PROGRESS_RE.pattern,
            PYTEST_URGENT_RE.pattern,
            PYTEST_SUMMARY_BANNER_RE.pattern,
            PYTEST_COLLECTED_RE.pattern,
        )
    )
)


def classify_pytest_line(line: str) -> Classification:
    """Classify a single non-TTY pytest output line.

    Order matters: failure summaries that *also* contain a percent token
    in their narrative (rare, but possible inside test names) must still
    classify as ``URGENT`` so they emit immediately. We check
    URGENT and SUMMARY before PROGRESS for that reason.
    """
    if PYTEST_URGENT_RE.search(line):
        return Classification(LineClass.URGENT)
    if PYTEST_SUMMARY_BANNER_RE.search(line):
        return Classification(LineClass.SUMMARY)
    if PYTEST_COLLECTED_RE.search(line):
        return Classification(LineClass.SUMMARY)
    match = PYTEST_PROGRESS_RE.search(line)
    if match:
        return Classification(
            LineClass.PROGRESS, progress_value=float(match.group(1))
        )
    return Classification(LineClass.NOISE)


def _pytest_argv(args: Sequence[str]) -> list[str]:
    """Build the underlying pytest invocation."""
    return [sys.executable, "-m", "pytest", *list(args)]


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="watch_pytest",
        description="Run pytest under a shared raw+progress watcher wrapper.",
        epilog=(
            "Full-suite shape: pass the two anchors 'runtime/api/ "
            "runtime/harness/' — never bare 'runtime/', which demotes "
            "runtime/api/conftest.py from initial-conftest status and "
            "fails collection. The wrapper refuses bare 'runtime/'."
        ),
        # We rely on the explicit ``--`` separator to split wrapper flags
        # from pytest pass-through, so disable argparse's own abbrev.
        allow_abbrev=False,
    )
    parser.add_argument(
        _watch_runner.PRINT_STREAMING_PAIR_FLAG,
        dest="print_streaming_pair",
        action="store_true",
        help="Print a ready-to-paste background command + progress-tail pair "
        "and exit. Mints fresh capture paths.",
    )
    parser.add_argument(
        "--raw-capture",
        type=Path,
        default=None,
        help="Explicit raw capture file path. Defaults to a helper-resolved "
        "path under the project scratch root.",
    )
    parser.add_argument(
        "--progress-capture",
        type=Path,
        default=None,
        help="Explicit progress capture file path. Defaults to a helper-"
        "resolved path under the project scratch root.",
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


def _strip_separator(passthrough: list[str]) -> list[str]:
    """Drop a leading ``--`` argparse left in the REMAINDER list."""
    if passthrough and passthrough[0] == "--":
        return passthrough[1:]
    return passthrough


def _extract_print_streaming_pair(argv: list[str]) -> tuple[list[str], bool]:
    """Pull ``--print-streaming-pair`` out of any position in ``argv``.

    ``passthrough`` uses ``nargs=argparse.REMAINDER``, which means the
    flag would otherwise reach pytest verbatim if placed after the
    ``--`` separator. Pre-extracting makes every position equivalent.
    """
    filtered: list[str] = []
    found = False
    for arg in argv:
        if arg == _watch_runner.PRINT_STREAMING_PAIR_FLAG:
            found = True
            continue
        filtered.append(arg)
    return filtered, found


def main(argv: Sequence[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    raw, print_streaming_pair_flag = _extract_print_streaming_pair(raw)
    ns = _parse_args(raw)
    if print_streaming_pair_flag:
        ns.print_streaming_pair = True
    pytest_args = _strip_separator(list(ns.passthrough))

    if _watch_pytest_args.is_nested_pytest_invocation(pytest_args):
        print(
            _watch_pytest_args.NESTED_PYTEST_REJECTION_MESSAGE,
            file=sys.stderr,
        )
        return 2

    if _watch_pytest_args.has_bare_runtime_path(pytest_args):
        print(
            _watch_pytest_args.BARE_RUNTIME_REJECTION_MESSAGE,
            file=sys.stderr,
        )
        return 2

    binding_refusal = _watch_worktree_binding.check()
    if binding_refusal is not None:
        print(binding_refusal, file=sys.stderr)
        return 3

    # Parallel-by-default: inject ``-n auto`` unless caller passed
    # ``--no-parallel`` or already supplied ``-n``/``--numprocesses``.
    # ``--no-parallel`` is a wrapper-level concept and never reaches pytest.
    no_parallel, pytest_args = split_no_parallel(pytest_args)
    pytest_args = apply_parallel_default(pytest_args, no_parallel=no_parallel)
    source_root = _source_pythonpath.repo_root(Path.cwd())
    pytest_env = apply_postgres_xdist_auto_env(pytest_args)
    pytest_env = _source_pythonpath.with_source_pythonpath(pytest_env, source_root)
    if (source_root / "packages" / "yoke-core" / "src" / "yoke_core").is_dir():
        import_refusal = _source_pythonpath.import_origin_refusal(
            source_root, env=pytest_env,
        )
        if import_refusal is not None:
            print(
                f"watch_pytest IMPORT-BINDING REFUSAL: {import_refusal}",
                file=sys.stderr,
            )
            return 3

    if ns.print_streaming_pair:
        raw_path, progress_path = _watch_runner.mint_capture_paths(KIND)
        _watch_runner.print_streaming_pair(
            kind=KIND,
            wrapper_module=WRAPPER_MODULE,
            wrapper_args=pytest_args,
            raw_capture=raw_path,
            progress_capture=progress_path,
            env_prefix=_source_pythonpath.shell_prefix(source_root),
        )
        return 0

    if ns.raw_capture is None or ns.progress_capture is None:
        minted_raw, minted_progress = _watch_runner.mint_capture_paths(KIND)
        raw_path = ns.raw_capture or minted_raw
        progress_path = ns.progress_capture or minted_progress
    else:
        raw_path = ns.raw_capture
        progress_path = ns.progress_capture

    warning = _watch_pytest_rootdir.rootdir_mismatch_warning(
        pytest_args, os.getcwd()
    )
    if warning:
        sys.stdout.write(warning)
        sys.stdout.flush()

    return _watch_runner.run_watcher(
        argv=_pytest_argv(pytest_args),
        classifier=classify_pytest_line,
        raw_capture=raw_path,
        progress_capture=progress_path,
        kind=KIND,
        env=pytest_env,
    )


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    sys.exit(main())
