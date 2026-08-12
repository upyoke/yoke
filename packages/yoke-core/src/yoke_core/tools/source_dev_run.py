"""Run one command from the current session's claimed source lane."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from yoke_core.domain import verification_tree_binding
from yoke_core.tools import _source_pythonpath


def _claimed_root() -> tuple[Path | None, str | None]:
    session_id = verification_tree_binding.ambient_session_id()
    if not session_id:
        return None, "no harness session identity is available"
    lookup = verification_tree_binding.resolve_claim_worktrees(session_id)
    if not lookup.reachable:
        return None, f"the work-claim lookup did not answer: {lookup.detail}"
    live = tuple(
        Path(path).resolve() for path in lookup.worktrees if Path(path).is_dir()
    )
    if not live:
        return None, (
            "this session has no live claimed lane; prepare the item worktree first"
        )
    if len(live) > 1:
        rendered = ", ".join(str(path) for path in live)
        return None, f"this session has multiple claimed lanes: {rendered}"
    root = _source_pythonpath.repo_root(live[0])
    if root != live[0]:
        return None, f"claimed lane is not a source checkout root: {live[0]}"
    return root, None


def run(command: Sequence[str]) -> int:
    args = list(command)
    if args[:1] == ["--"]:
        args = args[1:]
    if not args:
        print(
            "error: missing command; usage: yoke dev run -- <command>",
            file=sys.stderr,
        )
        return 2
    root, error = _claimed_root()
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
    print(f"source imports: {rendered}", file=sys.stderr)
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
            "lane and report every checkout-owned import origin."
        ),
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    parsed = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    return run(parsed.command)


__all__ = ["main", "run"]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
