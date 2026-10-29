"""Run source commands from a claimed lane, or a registered scanner in place.

The child uses the interpreter whose import origins were verified.
Candidate-bound QA refuses a switch to another source checkout.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from yoke_contracts.install_binding import SOURCE_DEV_RUN_ROOT_ENV
from yoke_core.domain import verification_tree_binding
from yoke_core.domain import source_python_environment
from yoke_core.tools import (
    _source_pythonpath,
    source_dev_candidate_binding,
    source_dev_scanner,
)
from yoke_core.tools.source_machine_home import isolated_machine_home

from yoke_core.tools.source_dev_main_audit import (
    MAIN_CHECKOUT_FALLBACK_EVENT as MAIN_CHECKOUT_FALLBACK_EVENT,
    record_main_checkout_fallback as _record_main_checkout_fallback,
)

MAIN_CHECKOUT_CLAIMED_TARGET_PREFIX = tuple(
    shlex.split(_source_pythonpath.INSTALL_BUNDLE_SYNC_RECIPE.partition("-- ")[2])[:-1]
)


def _lane_selectors(lanes: Sequence[Path]) -> str:
    return ", ".join(shlex.quote(f"--lane={path}") for path in lanes)


def _claimed_root(
    selected_lane: Path | str | None = None,
) -> tuple[Path | None, str | None, int | None]:
    session_id = verification_tree_binding.ambient_session_id()
    if not session_id:
        return (
            None,
            (
                "no harness session identity is available; run from an active "
                "harness session that owns a prepared Yoke item worktree"
            ),
            None,
        )
    lookup = verification_tree_binding.resolve_claim_worktrees(session_id)
    if not lookup.reachable:
        return (
            None,
            (
                f"the work-claim lookup did not answer: {lookup.detail}; restore "
                "the Yoke control-plane connection and retry"
            ),
            None,
        )
    live = tuple(
        dict.fromkeys(
            verification_tree_binding.local_worktree_path(path).resolve()
            for path in lookup.worktrees
            if verification_tree_binding.local_worktree_path(path).is_dir()
        )
    )
    if not live:
        return _mapped_main_source_root()
    source_lanes = tuple(
        lane
        for lane in live
        if _source_pythonpath.repo_root(lane) == lane
        and _source_pythonpath.is_yoke_shaped_tree(lane)
    )
    if not source_lanes:
        return _mapped_main_source_root()
    if selected_lane is not None:
        selected = verification_tree_binding.local_worktree_path(
            Path(selected_lane).expanduser()
        ).resolve()
        if selected in source_lanes:
            return selected, None, None
        return (
            None,
            (
                "selected lane is not a live claimed Yoke source checkout: "
                f"{selected}; choose one of: {_lane_selectors(source_lanes)}"
            ),
            None,
        )
    if len(source_lanes) > 1:
        return (
            None,
            (
                "this session has multiple claimed Yoke source lanes; choose one: "
                f"{_lane_selectors(source_lanes)}"
            ),
            None,
        )
    return source_lanes[0], None, None


def claimed_lane_root(
    selected_lane: Path | str | None = None,
) -> tuple[Path | None, str | None]:
    """Return a claimed lane; mapped main cannot prove a branch diff."""
    root, error, fallback_project_id = _claimed_root(selected_lane)
    if error or root is None:
        return None, error
    if fallback_project_id is not None:
        return None, (
            "this session has no live claimed Yoke source lane; "
            f"{root} is the mapped main checkout, not a lane"
        )
    return root, None


def _mapped_main_source_root() -> tuple[Path | None, str | None, int | None]:
    """Resolve the one machine-mapped checkout that is Yoke-shaped."""
    try:
        from yoke_cli.config.machine_config import configured_projects

        mappings = configured_projects(existing_only=False)
    except Exception as exc:
        return None, f"the machine checkout mapping could not be read: {exc}", None
    candidates: dict[Path, int] = {}
    for configured in mappings:
        checkout = configured.checkout.expanduser().resolve()
        if (
            checkout.is_dir()
            and _source_pythonpath.repo_root(checkout) == checkout
            and _source_pythonpath.is_yoke_shaped_tree(checkout)
        ):
            candidates[checkout] = configured.project_id
    if not candidates:
        return (
            None,
            (
                "this session has no live claimed Yoke source lane, and the machine "
                "mapping names no existing Yoke-shaped source checkout"
            ),
            None,
        )
    if len(candidates) > 1:
        rendered = ", ".join(str(path) for path in sorted(candidates))
        return (
            None,
            (
                "the machine mapping names multiple Yoke source checkouts; keep "
                f"exactly one mapped main checkout: {rendered}"
            ),
            None,
        )
    root, project_id = next(iter(candidates.items()))
    return root, None, project_id


def _claimed_target_signature(command: Sequence[str]) -> str | None:
    """Classify install-bundle sync when its destination is a claimed lane."""
    if tuple(command[:-1]) != MAIN_CHECKOUT_CLAIMED_TARGET_PREFIX:
        return None
    target = Path(command[-1]).expanduser().resolve()
    session_id = verification_tree_binding.ambient_session_id()
    lookup = verification_tree_binding.resolve_claim_worktrees(session_id)
    if not lookup.reachable:
        return None
    claimed = {
        verification_tree_binding.local_worktree_path(path).resolve()
        for path in lookup.worktrees
        if verification_tree_binding.local_worktree_path(path).is_dir()
    }
    if target not in claimed:
        return None
    return "claimed-target-python-module:install-bundle-sync"


def run(
    command: Sequence[str],
    *,
    lane: Path | str | None = None,
    allow_real_machine_home: bool = False,
) -> int:
    args = list(command)
    if args[:1] == ["--"]:
        args = args[1:]
    if not args:
        print(
            "error: missing command; usage: yoke dev run -- <command>",
            file=sys.stderr,
        )
        return 2
    root, error = source_dev_candidate_binding.resolve(lane)
    fallback_project_id = None
    if root is None and error is None:
        scanner = source_dev_scanner.scanner_root(args) if lane is None else None
        if scanner is not None:
            root, error = scanner
        else:
            root, error, fallback_project_id = (
                _claimed_root() if lane is None else _claimed_root(lane)
            )
    if error or root is None:
        print(f"error: {error}", file=sys.stderr)
        return 1
    authority_signature = None
    if fallback_project_id is not None:
        authority_signature = _claimed_target_signature(args)
        if authority_signature is None:
            print(
                "error: mapped-main source execution only permits "
                "claimed-target maintenance; prepare and claim a Yoke source "
                "lane for arbitrary commands",
                file=sys.stderr,
            )
            return 1
    try:
        with isolated_machine_home(
            dict(os.environ), allow_real=allow_real_machine_home
        ) as env:
            return _run_bound(args, root, fallback_project_id, authority_signature, env)
    except OSError as exc:
        print(
            f"source_machine_home_unavailable: {exc}; repair machine-home read "
            "permissions and temporary storage, then retry.",
            file=sys.stderr,
        )
        return 1


def _run_bound(args, root, fallback_project_id, authority_signature, env) -> int:
    try:
        binding = source_python_environment.resolve(root, env)
    except source_python_environment.SourceEnvironmentRefusal as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    env = binding.env
    env = _source_pythonpath.with_source_pythonpath(env, root)
    env[SOURCE_DEV_RUN_ROOT_ENV] = str(root)
    origins, origin_error = _source_pythonpath.import_origins(
        root, env=env, python=binding.python
    )
    if origin_error:
        print(f"error: {origin_error}", file=sys.stderr)
        print(
            f"recovery: {_source_pythonpath.SOURCE_RUN_RECIPE}",
            file=sys.stderr,
        )
        return 1
    rendered = ", ".join(f"{name}={path}" for name, path in origins.items())
    print(f"source checkout: {root}", file=sys.stderr)
    if fallback_project_id is not None:
        print(
            "source authority: mapped main checkout, registered operation "
            f"({authority_signature})",
            file=sys.stderr,
        )
        event_error = _record_main_checkout_fallback(
            session_id=verification_tree_binding.ambient_session_id(),
            root=root,
            project_id=fallback_project_id,
            command=args,
            authority_signature=str(authority_signature),
        )
        if event_error:
            print(f"error: {event_error}", file=sys.stderr)
            return 1
    print(f"source imports: {rendered}", file=sys.stderr)
    print(
        f"source environment: {json.dumps(binding.evidence, sort_keys=True)}",
        file=sys.stderr,
    )
    args = _source_pythonpath.bound_child_command(args, python=binding.python)
    try:
        returncode = subprocess.run(
            args, cwd=str(root), env=env, check=False
        ).returncode
        if returncode < 0:
            try:
                stopped_by = signal.Signals(-returncode).name
            except ValueError:
                stopped_by = f"signal {-returncode}"
            print(
                f"source_child_signalled: child stopped by {stopped_by} "
                f"({-returncode}); inspect the child command and retry",
                file=sys.stderr,
            )
            return 128 - returncode
        return returncode
    except OSError as exc:
        print(f"error: could not run {args[0]!r}: {exc}", file=sys.stderr)
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke dev run",
        description=(
            "Run a command from the current session's claimed Yoke source "
            "lane with disposable machine settings, and report every "
            "checkout-owned import origin. A registered read-only scanner "
            "runs from the current directory's Yoke source checkout without "
            "a session; claimed-target maintenance may use the mapped main "
            "checkout when no Yoke lane exists. A "
            "nested `yoke` or `python3` command uses the checkout's declared "
            "locked .venv; a drifted .venv first syncs to its unchanged lock. "
            "A missing environment, stale lock, failed sync, or incompatible "
            "Python refuses with lane-local recovery. Candidate-bound Command "
            "QA uses its bound candidate source by default; an explicit "
            "--lane pointing elsewhere refuses."
        ),
    )
    parser.add_argument(
        "--lane",
        type=Path,
        metavar="PATH",
        help="Select one live claimed Yoke source lane when several exist.",
    )
    parser.add_argument(
        "--allow-real-machine-home",
        action="store_true",
        help="Explicitly allow source code to write the real machine home.",
    )
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="Command to run in the lane, after --.",
    )
    parsed = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    return run(
        parsed.command,
        lane=parsed.lane,
        allow_real_machine_home=parsed.allow_real_machine_home,
    )


__all__ = ["claimed_lane_root", "main", "run"]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
