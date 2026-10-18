"""Derive public documentation breadcrumbs and immediate-child contents."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import posixpath
import tempfile
from urllib.parse import quote

from markdown_it import MarkdownIt
from yoke_cli.transport.response_evidence import wrapped_lines

from yoke_core.domain.documentation_navigation import (
    NavigationError,
    NavNode,
    breadcrumbs,
    iter_nodes,
    load_navigation,
)
from yoke_core.domain.workspace_authority import (
    assert_target_under_session_work_authority,
)


def _relative(page: str, target: str) -> str:
    return quote(posixpath.relpath(target, posixpath.dirname(page) or "."), safe="/")


def _block(name: str, body: str) -> str:
    return f"<!-- yoke:{name} -->\n{body}\n<!-- /yoke:{name} -->"


def _remove_blocks(markdown: str) -> str:
    lines = markdown.splitlines(keepends=True)
    remove: set[int] = set()
    opened: dict[str, int] = {}
    for token in MarkdownIt("commonmark").parse(markdown):
        if token.type != "html_block" or token.map is None:
            continue
        for index in range(*token.map):
            text = lines[index].strip()
            for name in ("breadcrumbs", "contents"):
                if text == f"<!-- yoke:{name} -->":
                    opened[name] = index
                elif text == f"<!-- /yoke:{name} -->" and name in opened:
                    remove.update(range(opened.pop(name), index + 1))
    return "".join(line for i, line in enumerate(lines) if i not in remove)


def render_page(tree: NavNode, node: NavNode, markdown: str) -> str:
    """Replace derived regions; preserve the authored teaching between them."""
    markdown = _remove_blocks(markdown).strip() + "\n"
    if node.path != tree.path:
        trail = breadcrumbs(tree, node.path)
        body = (
            " > ".join(
                f"[{n.title}]({_relative(node.path, n.path)})" for n in trail[:-1]
            )
            + f" > {node.title}"
        )
        tokens = MarkdownIt("commonmark").parse(markdown)
        heading = next(
            (t for t in tokens if t.type == "heading_open" and t.tag == "h1"), None
        )
        if heading is None or heading.map is None:
            raise ValueError(
                f"NAV_SCHEMA {node.path}: page needs an H1. Repair: add the page title as an H1"
            )
        lines = markdown.splitlines(keepends=True)
        end = heading.map[1]
        markdown = (
            "".join(lines[:end]).rstrip()
            + "\n\n"
            + _block("breadcrumbs", body)
            + "\n\n"
            + "".join(lines[end:]).lstrip("\n")
        )
    if node.children:
        contents = "\n".join(
            f"- [{child.title}]({_relative(node.path, child.path)}) — {child.summary}"
            for child in node.children
        )
        markdown = markdown.rstrip() + "\n\n" + _block("contents", contents) + "\n"
    return markdown


def _write(path: Path, content: str) -> None:
    assert_target_under_session_work_authority(path)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["write", "check", "measure"])
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--paths", nargs="+", help="select page path prefixes")
    args = parser.parse_args(argv)
    try:
        if not args.root.is_dir():
            raise ValueError(
                "documentation root is absent; supply an existing corpus root"
            )
        if args.command == "measure":
            pages = sorted(
                p
                for p in args.root.rglob("*.md")
                if not args.paths
                or any(
                    p.relative_to(args.root).as_posix().startswith(prefix)
                    for prefix in args.paths
                )
            )
            failures = 0
            for path in pages:
                original = path.read_text(encoding="utf-8")
                count = wrapped_lines(original)
                page = path.relative_to(args.root).as_posix()
                print(f"{page}: {count} wrapped lines, {len(original)} characters")
                if len(original) > 20_000:
                    print(
                        f"REVIEW {page}: above the advisory 20,000 characters; review readability and coherent topic boundaries"
                    )
                if count > 350:
                    print(
                        f"LINE_LIMIT {page}: above 350 wrapped lines. Repair: split at meaningful topic boundaries"
                    )
                    failures += 1
            return int(bool(failures))
        tree = load_navigation(args.root)
        nodes = [
            n
            for n in iter_nodes(tree)
            if not args.paths or any(n.path.startswith(p) for p in args.paths)
        ]
        failures = 0
        for node in nodes:
            path = args.root / node.path
            original = path.read_text(encoding="utf-8")
            rendered = render_page(tree, node, original)
            if original != rendered:
                if args.command == "write":
                    _write(path, rendered)
                else:
                    print(
                        f"STALE_NAV_BLOCK {node.path}: derived navigation differs. Repair: run documentation_render write --root {args.root}"
                    )
                    failures += 1
        if not failures:
            print(f"Navigation {args.command} OK: {len(nodes)} pages")
        return int(bool(failures))
    except NavigationError as exc:
        print(exc)
    except (OSError, UnicodeError, ValueError, RuntimeError) as exc:
        print(
            f"NAV_SCHEMA {args.root}: {exc}. Repair: fix the named page or restore claimed write authority and retry"
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
