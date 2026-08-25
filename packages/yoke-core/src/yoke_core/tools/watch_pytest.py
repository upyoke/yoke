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

import time
import sys
from pathlib import Path
from typing import Sequence

from yoke_core.domain import qa_gate_timeout, verification_tree_binding
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


def _pytest_argv(args: Sequence[str], *, cwd: Path | None = None) -> list[str]:
    """Build the underlying pytest invocation."""
    from yoke_core.tools.watch_pytest_project_python import pytest_argv

    return pytest_argv(args, cwd=cwd)


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


def _impacted_selection(
    base: str,
    *,
    bounded: bool = False,
    root: Path | None = None,
):
    """Selection for the current change, or None when there are no files."""
    from yoke_core.tools.watch_pytest_project_python import impacted_selection

    return impacted_selection(base, bounded=bounded, root=root)


def _impacted_tree() -> Path:
    from yoke_core.tools.watch_pytest_project_python import impacted_tree

    return impacted_tree()


def _selection_footer(selection, collected_items: int | None) -> str:
    from yoke_core.tools.watch_pytest_project_python import selection_footer

    return selection_footer(selection, collected_items)


def _selection_banner(selection) -> str:
    from yoke_core.tools.watch_pytest_project_python import selection_progress_banner

    return selection_progress_banner(selection)


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
    raw, widen_flag = _extract_wrapper_flag(raw, _watch_pytest_args.WIDEN_FLAG)
    raw, bounded_flag = _extract_wrapper_flag(raw, _watch_pytest_args.BOUNDED_FLAG)
    ns = _watch_pytest_args.parse_args(raw, prog)
    if print_streaming_pair_flag:
        ns.print_streaming_pair = True
    if allow_tree_mismatch_flag:
        ns.allow_tree_mismatch = True
    if widen_flag:
        ns.widen = True
    if bounded_flag:
        ns.bounded = True
    pytest_args = _strip_separator(list(ns.passthrough))

    selection = None
    run_root = Path.cwd().resolve()
    if ns.impacted is not None:
        run_root = _impacted_tree()
        selection = _impacted_selection(
            ns.impacted,
            bounded=not ns.widen,
            root=run_root,
        )
        if selection is None:
            return 0
        if getattr(selection, "bounded_deferral", False):
            print(
                _watch_pytest_args.format_would_widen_advisory(
                    rule=selection.fallback_rule,
                    trigger_paths=selection.trigger_paths,
                ),
                flush=True,
            )
        if not ns.print_streaming_pair:
            pytest_args = [*selection.pytest_paths(), *pytest_args]
    elif ns.widen:
        print(_watch_pytest_args.WIDEN_WITHOUT_IMPACTED, file=sys.stderr)
        return 2
    elif ns.bounded:
        print(_watch_pytest_args.BOUNDED_WITHOUT_IMPACTED, file=sys.stderr)
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

    invalid_selection = _watch_pytest_args.invalid_test_selection_diagnostic(
        pytest_args, run_root
    )
    if invalid_selection is not None:
        print(invalid_selection, file=sys.stderr)
        return _watch_pytest_args.PYTEST_USAGE_ERROR_EXIT_STATUS

    binding = verification_tree_binding.evaluate_run(
        surface=prog,
        tree=str(run_root),
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
    source_root = _source_pythonpath.repo_root(run_root)
    pytest_env = apply_postgres_xdist_auto_env(pytest_args)
    pytest_env = _source_pythonpath.with_source_pythonpath(pytest_env, source_root)
    # Already judged above; the child's startup check inherits that answer.
    pytest_env = _tree_binding_startup.with_binding_evaluated(pytest_env)
    if _source_pythonpath.is_yoke_shaped_tree(source_root):
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
        wrapper_options: list[str] = []
        if ns.impacted is not None:
            wrapper_options.extend(("--impacted", ns.impacted))
            wrapper_options.append(
                _watch_pytest_args.WIDEN_FLAG
                if ns.widen
                else _watch_pytest_args.BOUNDED_FLAG
            )
        if ns.allow_tree_mismatch:
            wrapper_options.append(verification_tree_binding.ALLOW_TREE_MISMATCH_FLAG)
        _watch_runner.print_streaming_pair(
            kind=KIND,
            wrapper_module=WRAPPER_MODULE,
            wrapper_args=pytest_args,
            wrapper_options=wrapper_options,
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

    warning = _watch_pytest_rootdir.rootdir_mismatch_warning(pytest_args, str(run_root))
    if warning:
        sys.stdout.write(warning)
        sys.stdout.flush()

    with gate_admission.admitted_gate(pytest_args, stream=sys.stdout):
        try:
            execution_timeout = qa_gate_timeout.execution_timeout_from_env()
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
            lines = []
            if selection is not None:
                lines.append(_selection_footer(selection, collected_items))
            zero_collection = _watch_pytest_args.zero_collection_diagnostic(
                pytest_args, collected_items, run_root
            )
            if zero_collection is not None:
                lines.append(zero_collection)
            return "\n".join(lines) or None

        exit_code = _watch_runner.run_watcher(
            argv=_pytest_argv(pytest_args, cwd=run_root),
            classifier=selection_classifier,
            raw_capture=raw_path,
            progress_capture=progress_path,
            kind=KIND,
            cwd=str(run_root),
            env=gate_admission.admitted_environment(pytest_env),
            timeout_seconds=execution_timeout,
            header_metadata=(
                _selection_banner(selection) if selection is not None else None
            ),
            footer_metadata=selection_footer,
        )
        _watch_pytest_wall_clock.report(time.monotonic() - started, raw_path)
    return exit_code


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    sys.exit(main())
