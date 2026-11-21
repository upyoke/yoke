"""Write or check the committed forbidden-edge baseline from a full tree scan.

Scans every Python file at a commit against the project's live
``architecture_model`` and writes the edges it finds to
``.yoke/architecture/forbidden-edge-baseline.json``. The merge gate refuses a
lane whose baseline gains entries, so regenerate only after removing edges or
changing the map, and commit the result with ``git add -f`` (the ``.yoke``
directory is ignored in stealth checkouts).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from yoke_core.domain.architecture_tree_scan import (
    BASELINE_PATH,
    forbidden_edges,
    render_baseline,
)
from yoke_core.domain.merge_architecture_edge_admission import (
    call_dispatcher,
    read_blobs,
    read_model,
    tree_paths,
)


def scan_commit(repo_root: str, commit: str, project: str, *, dispatch=None) -> str:
    """The baseline text for every forbidden edge at ``commit``."""
    model, refusal = read_model(project, dispatch or call_dispatcher)
    if refusal:
        raise SystemExit(refusal)
    if model is None:
        raise SystemExit(
            f"architecture_model_missing: {project} declares no architecture_model; "
            "declare one through Project Structure before writing a baseline"
        )
    paths = tree_paths(repo_root, commit)
    python = [path for path in paths if path.endswith(".py")]
    return render_baseline(
        forbidden_edges(model, read_blobs(repo_root, commit, python), paths)
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m yoke_core.tools.architecture_edge_baseline",
        description="Write (or --check) the forbidden-edge baseline from a full scan.",
    )
    parser.add_argument("--project", required=True, help="Project whose map to read.")
    parser.add_argument("--commit", default="HEAD", help="Commit to scan (default HEAD).")
    parser.add_argument("--repo", default=".", help="Checkout root (default: cwd).")
    parser.add_argument(
        "--check", action="store_true",
        help="Exit 1 when the written baseline differs from the scan; write nothing.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    repo = Path(args.repo).resolve()
    text = scan_commit(str(repo), args.commit, args.project)
    target = repo / BASELINE_PATH
    count = text.count("\n") - 2 if text != "[]\n" else 0
    if args.check:
        current = target.read_text(encoding="utf-8") if target.is_file() else None
        if current != text:
            print(
                f"{BASELINE_PATH} differs from a scan of {args.commit} ({count} edges); "
                f"regenerate it with `python -m yoke_core.tools.architecture_edge_baseline "
                f"--project {args.project}` and commit it with `git add -f`",
                file=sys.stderr,
            )
            return 1
        print(f"{BASELINE_PATH} matches {args.commit}: {count} edges")
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(f"wrote {BASELINE_PATH}: {count} edges at {args.commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main", "scan_commit"]
