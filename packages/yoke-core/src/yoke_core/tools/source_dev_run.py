"""Run one command from a claimed source lane or mapped main checkout."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from yoke_core.domain import verification_tree_binding
from yoke_core.tools import _source_pythonpath


MAIN_CHECKOUT_FALLBACK_EVENT = "SourceDevRunMainCheckoutFallback"
AMBIENT_PYTHON_NAMES = frozenset({"python", "python3"})


def _bound_command(args: list[str]) -> list[str]:
    """Replace an ambient python3 with this process's interpreter."""
    if args and Path(args[0]).name in AMBIENT_PYTHON_NAMES:
        return [sys.executable, *args[1:]]
    return args


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
            Path(path).resolve() for path in lookup.worktrees if Path(path).is_dir()
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
        selected = Path(selected_lane).expanduser().resolve()
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


def _record_main_checkout_fallback(
    *,
    session_id: str,
    root: Path,
    project_id: int,
    command: Sequence[str],
) -> str | None:
    """Record the audit boundary before a fallback child can touch main."""
    try:
        from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
        from yoke_contracts.api.function_call import TargetRef

        response = call_dispatcher(
            function_id="events.emit",
            target=TargetRef(kind="global"),
            payload={
                "name": MAIN_CHECKOUT_FALLBACK_EVENT,
                "kind": "audit",
                "type": "source_dev_run",
                "source_type": "script",
                "severity": "WARN",
                "outcome": "completed",
                "project": str(project_id),
                "context": {
                    "checkout": str(root),
                    "command_name": str(command[0]),
                    "argument_count": max(0, len(command) - 1),
                    "fallback_reason": "no_live_claimed_yoke_source_lane",
                    "read_only_intent": True,
                    "write_target_if_child_writes": "main",
                },
            },
            actor=build_actor(session_id=session_id),
        )
    except Exception as exc:
        return f"could not record main-checkout fallback: {exc}"
    if not response.success:
        detail = response.error.message if response.error else "unknown error"
        return f"could not record main-checkout fallback: {detail}"
    result = response.result or {}
    if not result.get("emitted"):
        return (
            "could not record main-checkout fallback: "
            f"{result.get('reason') or 'event was not emitted'}"
        )
    return None


def run(
    command: Sequence[str],
    *,
    lane: Path | str | None = None,
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
    root, error, fallback_project_id = (
        _claimed_root() if lane is None else _claimed_root(lane)
    )
    if error or root is None:
        print(f"error: {error}", file=sys.stderr)
        return 1
    env = _source_pythonpath.with_source_pythonpath(None, root)
    origins, origin_error = _source_pythonpath.import_origins(root, env=env)
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
            "source intent: mapped main checkout, read-only; a write-shaped "
            "child writes to MAIN",
            file=sys.stderr,
        )
        event_error = _record_main_checkout_fallback(
            session_id=verification_tree_binding.ambient_session_id(),
            root=root,
            project_id=fallback_project_id,
            command=args,
        )
        if event_error:
            print(f"error: {event_error}", file=sys.stderr)
            return 1
    print(f"source imports: {rendered}", file=sys.stderr)
    args = _bound_command(args)
    try:
        return subprocess.run(args, cwd=str(root), env=env, check=False).returncode
    except OSError as exc:
        print(f"error: could not run {args[0]!r}: {exc}", file=sys.stderr)
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke dev run",
        description=(
            "Run a command from the current session's claimed Yoke source "
            "lane, or its mapped main checkout when no lane remains, and "
            "report every checkout-owned import origin."
        ),
    )
    parser.add_argument(
        "--lane",
        type=Path,
        metavar="PATH",
        help="Select one live claimed Yoke source lane when several exist.",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    parsed = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    return run(parsed.command, lane=parsed.lane)


__all__ = ["main", "run"]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
