"""Command-shaped watcher for pytest runs.

The classifier relays progress, failures, collection notices, and terminal
summaries while preserving all other output in the raw capture.

Usage::

    # The change-scoped check. For a project that declares its CI workflow
    # this pushes the lane commit and runs the selection on CI; the machine
    # runs sessions, not tests.
    yoke watch pytest --impacted main --bounded

    # Run on this machine instead (order-sensitive debugging, an uncommitted
    # tree, an unreachable CI); local runs share one machine-wide worker
    # budget.
    yoke watch pytest --local --impacted main --bounded
    yoke watch pytest --local -- -n 0 runtime/api/test_x.py

    # Full suite — the three anchors, never bare ``runtime/`` (the wrapper
    # refuses it); CI's job, local only as the CI-outage fallback:
    yoke watch pytest --local -- runtime/api/ runtime/harness/ tests/

Pass BARE pytest args after ``--``; the wrapper supplies the pytest command
prefix and rejects ``-- python3 -m pytest …``. Local runs inject ``-n auto``
(pytest-xdist) unless the pass-through names ``-n``; use ``-n 0`` for
sequential debugging. The wrapper preserves the underlying exit code — a
remote run's mirrors the CI conclusion.
"""

from __future__ import annotations

import time
import sys
from pathlib import Path
from typing import Sequence

from yoke_contracts import schema_authority
from yoke_core.domain import qa_gate_timeout, verification_tree_binding
from yoke_core.domain import (
    verification_tree_binding_pytest_startup as _tree_binding_startup,
)
from yoke_core.tools import (
    _source_pythonpath,
    _watch_digest,
    _watch_pytest_args,
    _watch_pytest_rootdir,
    _watch_runner,
    gate_admission,
    pytest_remote_selection,
    pytest_worker_budget,
    watch_pytest_remote,
)
from yoke_core.tools._pytest_parallel import (
    apply_postgres_xdist_auto_env,
    apply_parallel_default,
    isolate_from_administering_machine_config,
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


def _route(ns, pytest_args: Sequence[str], run_root: Path):
    """Where this run executes. ``--widen`` is a local full sweep by definition."""
    return pytest_remote_selection.resolve_route(
        run_root,
        pytest_args=pytest_args,
        impacted_base=ns.impacted,
        local=ns.local or ns.widen,
    )


def main(argv: Sequence[str] | None = None, *, prog: str = DEFAULT_PROG) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    extract = _watch_pytest_args.extract_wrapper_flag
    raw, print_streaming_pair_flag = extract(raw, _watch_runner.PRINT_STREAMING_PAIR_FLAG)
    raw, allow_tree_mismatch_flag = extract(
        raw, verification_tree_binding.ALLOW_TREE_MISMATCH_FLAG
    )
    raw, widen_flag = extract(raw, _watch_pytest_args.WIDEN_FLAG)
    raw, bounded_flag = extract(raw, _watch_pytest_args.BOUNDED_FLAG)
    raw, local_flag = extract(raw, pytest_remote_selection.LOCAL_FLAG)
    raw, flush_seconds = _watch_digest.extract_flush_seconds(raw)
    ns = _watch_pytest_args.parse_args(raw, prog)
    ns.print_streaming_pair = ns.print_streaming_pair or print_streaming_pair_flag
    ns.allow_tree_mismatch = ns.allow_tree_mismatch or allow_tree_mismatch_flag
    ns.widen = ns.widen or widen_flag
    ns.bounded = ns.bounded or bounded_flag
    ns.local = ns.local or local_flag
    pytest_args = _strip_separator(list(ns.passthrough))

    # Claim the capture pair before preflight. The impacted selection,
    # the tree-binding lookup, and the import probe below each outlast a
    # follower's writer-evidence window, and a follower armed on a
    # capture nothing has claimed yet refuses a run that is merely slow
    # to reach its first line. Claiming here also makes every refusal
    # below a close, so the follower relays it and exits on the sentinel
    # -- including a capture flag misplaced after ``--``, whose named
    # file is exactly where that follower is waiting.
    misplaced = _watch_runner.misplaced_capture_flags(pytest_args)
    ns.raw_capture = ns.raw_capture or misplaced.get("--raw-capture")
    ns.progress_capture = ns.progress_capture or misplaced.get("--progress-capture")
    raw_path: Path | None = None
    progress_path: Path | None = None
    if not ns.print_streaming_pair:
        raw_path, progress_path = _watch_runner.bind_capture_paths(ns, KIND)

    def refuse(message: str, exit_code: int) -> int:
        return _watch_runner.refuse_claimed_capture(
            progress_path, KIND, message, exit_code
        )

    selection = None
    run_root = Path.cwd().resolve()
    if ns.impacted is not None:
        run_root = _impacted_tree()
    elif ns.widen:
        return refuse(_watch_pytest_args.WIDEN_WITHOUT_IMPACTED, 2)
    elif ns.bounded:
        return refuse(_watch_pytest_args.BOUNDED_WITHOUT_IMPACTED, 2)

    route = _route(ns, pytest_args, run_root)
    if isinstance(route, pytest_remote_selection.Refusal):
        return refuse(route.message, route.exit_code)
    remote = isinstance(route, pytest_remote_selection.RemoteRoute)
    if not remote:
        _watch_runner.note_claimed_capture(
            progress_path, f"# watch_{KIND} local-run: {route.reason}"
        )
    if ns.impacted is not None and not remote:
        _watch_runner.note_claimed_capture(
            progress_path,
            f"# watch_{KIND} impacted-selection: resolving the change against "
            f"{ns.impacted}; this runs before pytest starts",
        )
        selection = _impacted_selection(
            ns.impacted,
            bounded=not ns.widen,
            root=run_root,
        )
        if selection is None:
            return refuse(_watch_pytest_args.NO_SELECTED_TESTS, 0)
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

    shape_refusal = _watch_pytest_args.argument_shape_refusal(pytest_args, run_root)
    if shape_refusal is not None:
        return refuse(*shape_refusal)

    binding = verification_tree_binding.evaluate_run(
        surface=prog,
        tree=str(run_root),
        allow_mismatch=ns.allow_tree_mismatch,
    )
    if binding.notice is not None:
        print(binding.notice, file=sys.stderr)
    if binding.refusal is not None:
        return refuse(
            binding.refusal, _tree_binding_startup.TREE_BINDING_REFUSED_EXIT_STATUS
        )

    try:
        execution_timeout = qa_gate_timeout.execution_timeout_from_env()
    except ValueError as exc:
        return refuse(f"watch_pytest: {exc}", 2)

    if remote and not ns.print_streaming_pair:
        return watch_pytest_remote.run(
            route,
            kind=KIND,
            raw_capture=raw_path,
            progress_capture=progress_path,
            flush_seconds=_watch_digest.resolve_flush_seconds(ns, flush_seconds),
            timeout_seconds=execution_timeout,
        )

    # Parallel-by-default: inject ``-n auto`` unless caller passed
    # ``--no-parallel`` or already supplied ``-n``/``--numprocesses``.
    # ``--no-parallel`` is a wrapper-level concept and never reaches pytest.
    no_parallel, pytest_args = split_no_parallel(pytest_args)
    pytest_args = apply_parallel_default(pytest_args, no_parallel=no_parallel)
    source_root = _source_pythonpath.repo_root(run_root)
    pytest_env = apply_postgres_xdist_auto_env(
        pytest_args,
        isolate_from_administering_machine_config(
            schema_authority.environment_without_administering_selection()
        ),
    )
    pytest_env = _source_pythonpath.with_source_pythonpath(pytest_env, source_root)
    # Already judged above; the child's startup check inherits that answer.
    pytest_env = _tree_binding_startup.with_binding_evaluated(pytest_env)
    if _source_pythonpath.is_yoke_shaped_tree(source_root):
        import_refusal = _source_pythonpath.import_origin_refusal(
            source_root,
            env=pytest_env,
        )
        if import_refusal is not None:
            return refuse(f"watch_pytest IMPORT-BINDING REFUSAL: {import_refusal}", 3)

    if ns.print_streaming_pair:
        raw_path, progress_path = _watch_runner.mint_capture_paths(KIND)
        wrapper_options = _watch_digest.streaming_pair_options(flush_seconds)
        if ns.impacted is not None:
            wrapper_options.extend(("--impacted", ns.impacted))
            wrapper_options.append(
                _watch_pytest_args.WIDEN_FLAG
                if ns.widen
                else _watch_pytest_args.BOUNDED_FLAG
            )
        if ns.local:
            wrapper_options.append(pytest_remote_selection.LOCAL_FLAG)
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

    # Bound above, before preflight; the print branch returned already.
    warning = _watch_pytest_rootdir.rootdir_mismatch_warning(pytest_args, str(run_root))
    if warning:
        sys.stdout.write(warning)
        sys.stdout.flush()

    with gate_admission.admitted_gate(pytest_args, stream=sys.stdout), (
        pytest_worker_budget.granted_workers(pytest_args, pytest_env, stream=sys.stdout)
    ) as grant:
        pytest_args = grant.apply(pytest_args)
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
            flush_seconds=_watch_digest.resolve_flush_seconds(ns, flush_seconds),
            cwd=str(run_root),
            env=grant.environment(gate_admission.admitted_environment(pytest_env)),
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
