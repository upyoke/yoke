"""Render or check the Yoke teaching prototype.

Run from a Yoke source checkout:

    yoke dev run -- python3 docs/teaching/tools/build.py          # rebuild views
    yoke dev run -- python3 docs/teaching/tools/build.py --check  # verify only

People run `yoke dev yokepedia` to build and open the page. The one generated
file, views/yokepedia.html, is untracked and self-contained: it embeds the
graph, source documents, research records and build information.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path, PurePosixPath

import inventory
import privacy
from model import (
    MODEL_ROOT,
    REBUILD,
    TEACHING_ROOT,
    Problem,
    dump,
    load,
    model_files,
    validate,
)
from limits import LINE_LIMIT, wrapped_lines
from guide_data import GuideData
from render_explorer import build_explorer

VIEWS_ROOT = TEACHING_ROOT / "views"
LIVE_ROOT = TEACHING_ROOT / "live"
FILE_SPLIT = "split it into a new file at a meaningful boundary"
_HREF = re.compile(r'href="([^"]*)"')
_ID = re.compile(r'id="([^"]*)"')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate the model and build views in memory without writing",
    )
    args = parser.parse_args(argv)

    model = load()
    live = inventory.live_registries()
    files = inventory.tracked_files()
    docs = inventory.documents(files)
    validate(model, live, set(files))
    if model.problems:
        return report(model.problems, check=args.check)
    graph = model.docs_graph
    pages = GuideData(model, live, docs, lambda path: inventory.area_of(path, graph))
    views: dict[str, str] = {}
    scanned = build_explorer(views, pages)
    check_links(model, views, set(files))

    canonical = {
        path: dump(json.loads(path.read_text(encoding="utf-8")))
        for path in model_files()
        if not _unreadable(model, path)
    }
    if args.check:
        check_canonical_model(model, canonical)
    limits_and_privacy(model, scanned)
    if not args.check and not model.problems:
        publish(model, views)
    return report(model.problems, check=args.check)


def _unreadable(model, path: Path) -> bool:
    return any(
        p.code == "MODEL_UNREADABLE" and p.where.endswith(path.name)
        for p in model.problems
    )


def check_links(model, views: dict[str, str], repo_files: set[str]) -> None:
    """Every href must reach a view (and its anchor) or a tracked file."""
    anchors = {path: set(_ID.findall(text)) for path, text in views.items()}
    for path, text in views.items():
        for target in _HREF.findall(text):
            target = target.replace("&amp;", "&")
            file_part, _, anchor = target.partition("#")
            resolved = (
                _resolve(PurePosixPath(path).parent, file_part) if file_part else path
            )
            if resolved in views:
                if anchor and anchor not in anchors.get(resolved, set()):
                    model.problem(
                        "DANGLING_ANCHOR",
                        f"docs/teaching/views/{path}",
                        f"{target} names a missing anchor",
                    )
                continue
            repo_path = _resolve(
                PurePosixPath("docs/teaching/views") / PurePosixPath(path).parent,
                file_part,
            )
            if repo_path not in repo_files:
                model.problem(
                    "DANGLING_LINK",
                    f"docs/teaching/views/{path}",
                    f"{target} does not resolve to a view or tracked file",
                )


def _resolve(base: PurePosixPath, target: str) -> str:
    return inventory._normalize(base / target)


def check_canonical_model(model, canonical: dict) -> None:
    for path, text in canonical.items():
        if path.read_text(encoding="utf-8") != text:
            model.problem(
                "MODEL_NOT_CANONICAL",
                path.relative_to(TEACHING_ROOT).as_posix(),
                "formatting differs from the canonical layout; run "
                "`yoke dev run -- python3 docs/teaching/tools/convert_model.py`",
            )


def publish(model, views: dict[str, str]) -> None:
    """Swap each validated page in, then delete obsolete generated files.

    A failed write keeps the last good page; nothing is removed until every
    page is in place.
    """
    try:
        VIEWS_ROOT.mkdir(parents=True, exist_ok=True)
        for name, text in views.items():
            fd, temp = tempfile.mkstemp(prefix=f".{name}.", suffix=".tmp", dir=VIEWS_ROOT)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(text)
                os.chmod(temp, 0o644)
                os.replace(temp, VIEWS_ROOT / name)
            finally:
                Path(temp).unlink(missing_ok=True)
        for stale in VIEWS_ROOT.iterdir():
            if stale.name in views or stale.name.endswith(".tmp"):
                continue
            shutil.rmtree(stale) if stale.is_dir() else stale.unlink()
        if LIVE_ROOT.exists():
            shutil.rmtree(LIVE_ROOT)
    except OSError as exc:
        model.problem(
            "VIEWS_WRITE_FAILED",
            "docs/teaching/views",
            f"{exc}; make docs/teaching/views writable, then rebuild",
        )


def limits_and_privacy(model, generated: dict[str, str]) -> None:
    """Authored files keep the line limit; every file, generated too, is privacy-scanned."""
    texts = {f"views/{path}": text for path, text in generated.items()}
    for path in TEACHING_ROOT.rglob("*"):
        rel = path.relative_to(TEACHING_ROOT).as_posix()
        if (
            path.is_file()
            and not rel.startswith(("views/", "live/", "tools/__pycache__"))
            and rel not in texts
        ):
            texts[rel] = path.read_text(encoding="utf-8", errors="replace")
    for rel, text in sorted(texts.items()):
        lines = wrapped_lines(text)
        if lines > LINE_LIMIT and not rel.startswith("views/"):
            model.problem(
                "LINE_LIMIT",
                f"docs/teaching/{rel}",
                f"{lines} lines at 80 columns exceeds {LINE_LIMIT}; {FILE_SPLIT}",
            )
        for number, line in enumerate(text.splitlines(), start=1):
            for label, pattern in privacy.PATTERNS:
                if pattern.search(line):
                    model.problem(
                        "PRIVATE_MATERIAL",
                        f"docs/teaching/{rel}:{number}",
                        f"{label}; {privacy.RECOVERY}",
                    )


def report(problems: list[Problem], *, check: bool) -> int:
    if not problems:
        print("teaching prototype: " + ("check passed" if check else "views rebuilt"))
        return 0
    for problem in problems:
        print(problem.render())
    print(
        f"\n{len(problems)} problem(s). Fix the model under {MODEL_ROOT.relative_to(TEACHING_ROOT.parents[1])}, "
        f"then run `{REBUILD}` and re-run with --check."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
