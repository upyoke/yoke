from __future__ import annotations

import sys
from pathlib import Path

from yoke_core.domain.lock_helper import acquire_lock, release_lock
from yoke_core.domain.worktree import resolve_main_root

USAGE = """Usage: python3 -m yoke_core.domain.write_to_main <append|write> <relative-path>

Subcommands:
  append  - Append stdin to file at main repo root
  write   - Overwrite file at main repo root with stdin

Path is relative to the main repo root.
Content is read from stdin (works with heredocs)."""


class WriteToMainError(RuntimeError):
    pass


def resolve_target_path(
    relative_path: str,
    *,
    cwd: str | None = None,
    claude_project_dir: str | None = None,
) -> tuple[Path, Path]:
    main_root = Path(
        resolve_main_root(cwd=cwd, claude_project_dir=claude_project_dir)
    ).resolve()
    target = (main_root / relative_path).resolve()
    if not target.parent.is_dir():
        raise WriteToMainError(
            f"Error: Directory does not exist: {target.parent}\n"
            "Hint: Check for path misspellings "
            "(e.g., 'ouraboros' vs 'ouroboros', 'runtime/yoke/' prefix doubling)."
        )
    return main_root, target


def normalize_content(stdin_text: str) -> str:
    return f"{stdin_text.rstrip(chr(10))}\n"


def write_to_main(
    mode: str,
    relative_path: str,
    stdin_text: str,
    *,
    cwd: str | None = None,
    claude_project_dir: str | None = None,
) -> Path:
    if mode not in {"append", "write"}:
        raise WriteToMainError(f"Error: Unknown subcommand '{mode}'")
    if not relative_path:
        raise WriteToMainError("Error: Missing file path argument")

    main_root, target = resolve_target_path(
        relative_path,
        cwd=cwd,
        claude_project_dir=claude_project_dir,
    )
    config_path = main_root / "runtime" / "config"
    lock_dir = Path(f"{target}.lock")
    payload = normalize_content(stdin_text)

    if not acquire_lock(lock_dir, config_path):
        raise WriteToMainError(
            f"Error: Could not acquire lock after configured retries: {lock_dir}"
        )
    try:
        if mode == "append":
            with target.open("a", encoding="utf-8") as handle:
                handle.write(payload)
        else:
            target.write_text(payload, encoding="utf-8")
    finally:
        release_lock(lock_dir)
    return target


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("Error: Missing subcommand", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 1

    mode = args.pop(0)
    if mode not in {"append", "write"}:
        print(f"Error: Unknown subcommand '{mode}'", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 1

    if not args:
        print("Error: Missing file path argument", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 1

    relative_path = args.pop(0)
    try:
        write_to_main(
            mode,
            relative_path,
            sys.stdin.read(),
            cwd=str(Path.cwd()),
            claude_project_dir=None,
        )
    except WriteToMainError as exc:
        print(str(exc), file=sys.stderr)
        if "Directory does not exist:" not in str(exc):
            print(USAGE, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
