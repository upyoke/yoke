"""Render or check the Yoke teaching prototype.

Run from a Yoke source checkout:

    yoke dev run -- python3 docs/teaching/tools/build.py          # rebuild views
    yoke dev run -- python3 docs/teaching/tools/build.py --check  # verify only
    yoke dev run -- python3 docs/teaching/tools/build.py --live   # + live pages

Generated views are untracked and depend only on the model. ``--live`` also
writes the command crosswalk and documentation graph, which read the live registries and git
tree, into the untracked ``docs/teaching/live/`` directory.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath

import inventory
import privacy
from model import (
    MODEL_ROOT,
    REBUILD,
    TEACHING_ROOT,
    Problem,
    coverage,
    dump,
    load,
    model_files,
    validate,
)
from render import LINE_LIMIT, wrapped_lines
from render_pages import LIVE, Pages
from render_overview import index_page
from render_explorer import build_explorer

VIEWS_ROOT = TEACHING_ROOT / "views"
LIVE_ROOT = TEACHING_ROOT / "live"
INTRO = (
    "The maintained catalog of what Yoke teaches agents and people, up front "
    "and in each situation: concepts, the surfaces that carry teaching, the "
    "scenarios that need it, boundaries, evidence and gaps. Mapped means a "
    "direct teaching link; it never proves the teaching works."
)
PAGE_SPLIT = (
    "move a large child branch to its own page by setting the record field "
    "`page` on that child and its descendants (or on surface and scenario "
    'parts), e.g. "page": "qa-cases" in model/concepts/qa-plans/cases.json; '
    "keep record content unchanged"
)
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
    parser.add_argument(
        "--live",
        action="store_true",
        help="also write the live command and docs-graph pages",
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
    pages = Pages(
        model, live, coverage(model), docs, lambda path: inventory.area_of(path, graph)
    )
    views: dict[str, str] = {
        "style.css": (Path(__file__).parent / "style.css").read_text(encoding="utf-8")
    }
    pages.concept_pages(views)
    pages.owned_pages(
        views, "surfaces", model.surfaces, model.teaching, "Teaching surfaces"
    )
    pages.owned_pages(views, "scenarios", model.scenarios, model.lessons, "Scenarios")
    pages.evidence_pages(views)
    pages.record_page(views, "boundaries.html", "Locked boundaries", model.boundaries)
    pages.record_page(views, "gaps.html", "Gaps", model.gaps)
    pages.docs_pages(views)
    pages.commands_page(views)
    index_page(views, INTRO)
    build_explorer(views, pages)
    live_pages = {
        path[len(LIVE) :]: views.pop(path)
        for path in list(views)
        if path.startswith(LIVE)
    }
    check_links(model, views, set(files))

    canonical = {
        path: dump(json.loads(path.read_text(encoding="utf-8")))
        for path in model_files()
        if not _unreadable(model, path)
    }
    if args.check:
        check_canonical_model(model, canonical)
    else:
        _replace_tree(VIEWS_ROOT, views)
    if args.live:
        _replace_tree(LIVE_ROOT, live_pages)
    limits_and_privacy(model, views)
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


def _replace_tree(root: Path, pages: dict[str, str]) -> None:
    """Write ``pages`` under ``root`` and delete HTML pages no longer generated."""
    for stale in root.rglob("*.html"):
        if stale.relative_to(root).as_posix() not in pages:
            stale.unlink()
    for path, text in pages.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


def limits_and_privacy(model, views: dict[str, str]) -> None:
    texts = {f"views/{path}": text for path, text in views.items()}
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
        if lines > LINE_LIMIT:
            model.problem(
                "LINE_LIMIT",
                f"docs/teaching/{rel}",
                f"{lines} lines at 80 columns exceeds {LINE_LIMIT}; "
                + (PAGE_SPLIT if rel.startswith("views/") else FILE_SPLIT),
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
