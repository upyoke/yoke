"""Generate the Yoke shell migration inventory.

Emits a canonical Markdown inventory for every ``.sh`` file in the repo,
including a file-level migration/disposition row and function-level detail for
larger or multi-responsibility scripts.

The implementation is split across four sibling modules — scanner, classifier,
routing rules, zero-shell closeout lane map, and reporter — with this module owning only
the CLI entry point.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from yoke_core.tools.shell_inventory_report import load_shell_files, render_markdown
from yoke_core.tools.shell_inventory_scan import repo_root


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the shell migration inventory.")
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Repo root to scan (defaults to tracked files in the current worktree root).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Where to write the Markdown inventory (defaults to docs/archive/shell-inventory.md).",
    )
    args = parser.parse_args()

    default_root = repo_root(Path(__file__).resolve())
    root = Path(args.repo_root).resolve() if args.repo_root else default_root
    output = (
        Path(args.output).resolve()
        if args.output
        else root / "docs" / "archive" / "shell-inventory.md"
    )

    shell_files = load_shell_files(root)
    output.write_text(render_markdown(root, shell_files), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
