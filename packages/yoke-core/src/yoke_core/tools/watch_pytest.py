"""Command-shaped watcher for pytest runs.

The classifier relays progress, failures, collection notices, and terminal
summaries while preserving all other output in the raw capture.

Usage::

    # Direct execution (Codex / shell): streams filtered progress to stdout
    # while preserving full output in the raw capture. Pass BARE pytest
    # args after ``--``; the wrapper supplies the pytest command prefix.
    yoke watch pytest -- runtime/api/

    # Full suite — pass the three anchors, never bare ``runtime/``
    # (which demotes runtime/api/conftest.py from initial-conftest status
    # and fails collection; the wrapper refuses it):
    yoke watch pytest -- runtime/api/ runtime/harness/ tests/

    # Print the ready-to-paste streaming pair:
    yoke watch pytest --print-streaming-pair -- runtime/api/

    # Serial mode (debug order-sensitive failures):
    yoke watch pytest -- -n 0 runtime/api/

Parallel-by-default: ``-n auto`` (pytest-xdist) is injected unless the caller
passes its own ``-n``/``--numprocesses`` in the pass-through. Use ``-n 0`` for
sequential debugging. The wrapper preserves the underlying ``pytest`` exit
code so callers can still branch on success/failure.

Do NOT pass a full pytest command-shape after ``--``. The wrapper rejects
``-- python3 -m pytest …`` variants before invoking the underlying runner.
"""

from __future__ import annotations

import argparse
import os
import time
import sys
from dataclasses import replace
from pathlib import Path
from typing import Sequence

from yoke_core.domain import test_gate_timeout, verification_tree_binding
from yoke_core.domain import (
    verification_tree_binding_pytest_startup as _tree_binding_startup,
)
from yoke_core.tools import (
    _source_pythonpath,
    _watch_pytest_args,
    _watch_pytest_rootdir,
    _watch_runner,
    gate_admission,
)
from yoke_core.tools._pytest_parallel import (
    apply_postgres_xdist_auto_env,
    apply_parallel_default,
    split_no_parallel,
)
from yoke_core.tools import _watch_pytest_wall_clock

# Re-exported so callers keep one import site for the classifier.
from yoke_core.tools._watch_pytest_classify import (  # noqa: F401
    PYTEST_COLLECTED_RE,
    PYTEST_PROGRESS_PATTERN,
    PYTEST_PROGRESS_RE,
    PYTEST_SUMMARY_BANNER_RE,
    PYTEST_URGENT_RE,
    classify_pytest_line,
    pytest_collected_item_count,
)

WRAPPER_MODULE = "yoke_core.tools.watch_pytest"
KIND = "pytest"
# argparse prog for a direct module invocation; the CLI adapter passes the
# ``yoke watch pytest`` form so help reads back the command as typed.
DEFAULT_PROG = "watch_pytest"


def _pytest_argv(args: Sequence[str]) -> list[str]:
    """Build the underlying pytest invocation."""
    return [sys.executable, "-m", "pytest", *list(args)]


def _parse_args(
    argv: Sequence[str],
    prog: str = DEFAULT_PROG,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Run pytest under a shared raw+progress watcher wrapper.",
        epilog=(
            "Full-suite shape: pass the three anchors 'runtime/api/ "
            "runtime/harness/ tests/' — never bare 'runtime/', which "
            "demotes runtime/api/conftest.py from initial-conftest status "
            "and fails collection. The wrapper refuses bare 'runtime/'."
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
        "--impacted",
        nargs="?",
        const="main",
        default=None,
        metavar="BASE",
        help="Run only the tests reachable from this branch's changes "
        "(default base: main). Falls back to the full sweep whenever "
        "reachability cannot bound the change. An accelerator for "
        "iteration — merge still runs the full sweep.",
    )
    parser.add_argument(
        "--bounded",
        action="store_true",
        help="With --impacted, never widen to the full sweep: run the "
        "subset reachability can still compute and report why coverage "
        "is partial. The iteration shape when a QA case run will be the "
        "one full execution for this tree.",
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


def _strip_separator(passthrough: list[str]) -> list[str]:
    """Drop a leading ``--`` argparse left in the REMAINDER list."""
    if passthrough and passthrough[0] == "--":
        return passthrough[1:]
    return passthrough


def _extract_wrapper_flag(argv: list[str], flag: str) -> tuple[list[str], bool]:
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


def _impacted_selection(base: str, *, bounded: bool = False):
    """Selection for the current change, or None when there are no files."""
    from yoke_core.tools import impacted_tests

    selection = impacted_tests.selection_for(
        _source_pythonpath.repo_root(Path.cwd()), base, bounded=bounded
    )
    scope = "full sweep" if selection.full_sweep else "impacted"
    print(
        f"watch_pytest {scope}: {selection.reason}; {selection.count_summary()}",
        flush=True,
    )
    # Structured companion to the prose reason above. Both land in the run's
    # captures; only this one can be grouped across runs to tell legitimate
    # core churn from a file kind reachability never modelled.
    print(f"watch_pytest {selection.telemetry()}", flush=True)
    return selection if selection.pytest_paths() else None


def _selection_footer(selection, collected_items: int | None) -> str:
    all_files = selection.full_sweep or len(selection.files) == selection.total_files
    total_items = collected_items if all_files else None
    counted = replace(
        selection, selected_items=collected_items, total_items=total_items
    )
    return f"# watch_pytest selection-summary: {counted.count_summary()}"


def main(argv: Sequence[str] | None = None, *, prog: str = DEFAULT_PROG) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    raw, print_streaming_pair_flag = _extract_wrapper_flag(
        raw,
        _watch_runner.PRINT_STREAMING_PAIR_FLAG,
    )
    raw, allow_tree_mismatch_flag = _extract_wrapper_flag(
        raw,
        verification_tree_binding.ALLOW_TREE_MISMATCH_FLAG,
    )
    ns = _parse_args(raw, prog)
    if print_streaming_pair_flag:
        ns.print_streaming_pair = True
    if allow_tree_mismatch_flag:
        ns.allow_tree_mismatch = True
    pytest_args = _strip_separator(list(ns.passthrough))

    selection = None
    if ns.impacted is not None:
        selection = _impacted_selection(ns.impacted, bounded=ns.bounded)
        if selection is None:
            return 0
        pytest_args = [*selection.pytest_paths(), *pytest_args]
    elif ns.bounded:
        print(
            "watch_pytest: --bounded only applies with --impacted",
            file=sys.stderr,
        )
        return 2

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

    binding = verification_tree_binding.evaluate_run(
        surface=prog,
        allow_mismatch=ns.allow_tree_mismatch,
    )
    if binding.notice is not None:
        print(binding.notice, file=sys.stderr)
    if binding.refusal is not None:
        print(binding.refusal, file=sys.stderr)
        return _tree_binding_startup.TREE_BINDING_REFUSED_EXIT_STATUS

    # Parallel-by-default: inject ``-n auto`` unless caller passed
    # ``--no-parallel`` or already supplied ``-n``/``--numprocesses``.
    # ``--no-parallel`` is a wrapper-level concept and never reaches pytest.
    no_parallel, pytest_args = split_no_parallel(pytest_args)
    pytest_args = apply_parallel_default(pytest_args, no_parallel=no_parallel)
    source_root = _source_pythonpath.repo_root(Path.cwd())
    pytest_env = apply_postgres_xdist_auto_env(pytest_args)
    pytest_env = _source_pythonpath.with_source_pythonpath(pytest_env, source_root)
    # Already judged above; the child's startup check inherits that answer.
    pytest_env = _tree_binding_startup.with_binding_evaluated(pytest_env)
    if (source_root / "packages" / "yoke-core" / "src" / "yoke_core").is_dir():
        import_refusal = _source_pythonpath.import_origin_refusal(
            source_root,
            env=pytest_env,
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
        )
        return 0

    if ns.raw_capture is None or ns.progress_capture is None:
        minted_raw, minted_progress = _watch_runner.mint_capture_paths(KIND)
        raw_path = ns.raw_capture or minted_raw
        progress_path = ns.progress_capture or minted_progress
    else:
        raw_path = ns.raw_capture
        progress_path = ns.progress_capture

    warning = _watch_pytest_rootdir.rootdir_mismatch_warning(pytest_args, os.getcwd())
    if warning:
        sys.stdout.write(warning)
        sys.stdout.flush()

    with gate_admission.admitted_gate(pytest_args, stream=sys.stdout):
        try:
            execution_timeout = test_gate_timeout.execution_timeout_from_env()
        except ValueError as exc:
            print(f"watch_pytest: {exc}", file=sys.stderr)
            return 2
        started = time.monotonic()
        collected_items = None

        def selection_classifier(line: str):
            nonlocal collected_items
            count = pytest_collected_item_count(line)
            if count is not None:
                collected_items = count
            return classify_pytest_line(line)

        def selection_footer() -> str | None:
            if selection is None:
                return None
            return _selection_footer(selection, collected_items)

        exit_code = _watch_runner.run_watcher(
            argv=_pytest_argv(pytest_args),
            classifier=selection_classifier,
            raw_capture=raw_path,
            progress_capture=progress_path,
            kind=KIND,
            env=gate_admission.admitted_environment(pytest_env),
            timeout_seconds=execution_timeout,
            footer_metadata=selection_footer,
        )
        _watch_pytest_wall_clock.report(time.monotonic() - started, raw_path)
    return exit_code


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    sys.exit(main())
