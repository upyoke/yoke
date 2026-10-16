"""CommonMark heading identities and links resolved from their containing page."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
import re
import unicodedata
from typing import Iterable
from urllib.parse import unquote, urlsplit, urlunsplit

from markdown_it import MarkdownIt


@dataclass(frozen=True)
class MarkdownLink:
    target: str
    text: str


@dataclass(frozen=True)
class ResolvedLink:
    path: str
    query: str = ""
    fragment: str = ""
    external: bool = False

    @property
    def target(self) -> str:
        if self.external:
            return self.path
        return urlunsplit(("", "", self.path, self.query, self.fragment))


@dataclass(frozen=True)
class LinkRefusal:
    code: str
    target: str
    detail: str
    repair: str

    def __str__(self) -> str:
        return f"{self.code} {self.target}: {self.detail}. Repair: {self.repair}"


def _visible(tokens) -> str:
    return "".join(
        token.content
        if token.type in ("text", "code_inline")
        else _visible(token.children or [])
        if token.type == "image"
        else " "
        if token.type in ("softbreak", "hardbreak")
        else ""
        for token in tokens
    )


def heading_ids(markdown: str) -> list[str]:
    tokens = MarkdownIt("commonmark").parse(markdown)
    emitted: set[str] = set()
    result: list[str] = []
    for index, token in enumerate(tokens):
        if token.type != "heading_open":
            continue
        visible = _visible(tokens[index + 1].children or [])
        text = unicodedata.normalize("NFC", visible).lower()
        text = "".join(
            c
            for c in text
            if unicodedata.category(c)[0] in "LMN" or c in "-_" or c.isspace()
        )
        base = re.sub(r"\s+", "-", text).strip("-") or "section"
        candidate = base
        suffix = 0
        while candidate in emitted:
            suffix += 1
            candidate = f"{base}-{suffix}"
        emitted.add(candidate)
        result.append(candidate)
    return result


def links(markdown: str) -> list[MarkdownLink]:
    result: list[MarkdownLink] = []
    for token in MarkdownIt("commonmark").parse(markdown):
        children = token.children or []
        for index, child in enumerate(children):
            if child.type == "link_open":
                end = next(
                    i
                    for i in range(index + 1, len(children))
                    if children[i].type == "link_close"
                )
                result.append(
                    MarkdownLink(
                        child.attrGet("href") or "", _visible(children[index + 1 : end])
                    )
                )
            elif child.type == "image":
                result.append(
                    MarkdownLink(
                        child.attrGet("src") or "", _visible(child.children or [])
                    )
                )
    return result


def resolve_link(page: str, target: str) -> ResolvedLink:
    """Normalize a local URL without losing its query or encoded fragment."""
    split = urlsplit(target)
    if split.scheme or split.netloc or target.startswith("//"):
        return ResolvedLink(target, external=True)
    if not split.path:
        return ResolvedLink(page, split.query, split.fragment)
    path = unquote(split.path)
    if path.startswith("/") or "\\" in path or "\x00" in path:
        raise ValueError(
            f"LINK_ESCAPES {target}: use a relative path inside the documentation root"
        )
    parts = page.split("/")[:-1]
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                raise ValueError(
                    f"LINK_ESCAPES {target}: use a relative path inside the documentation root"
                )
            parts.pop()
        else:
            parts.append(part)
    return ResolvedLink("/".join(parts), split.query, split.fragment)


class _HeadingHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids: list[str] = []

    def handle_starttag(self, tag, attrs):
        if re.fullmatch(r"h[1-6]", tag):
            self.ids.extend(value or "" for key, value in attrs if key == "id")


def _html_heading_ids(markdown: str) -> list[str]:
    parser = _HeadingHTML()
    for token in MarkdownIt("commonmark").parse(markdown):
        if token.type == "html_block":
            parser.feed(token.content)
        for child in token.children or []:
            if child.type == "html_inline":
                parser.feed(child.content)
    return parser.ids


def validate_links(root: Path, pages: Iterable[str]) -> list[LinkRefusal]:
    root = Path(root).resolve()
    refusals: list[LinkRefusal] = []
    for page in pages:
        source = root / page
        if not source.resolve().is_relative_to(root) or not source.is_file():
            refusals.append(
                LinkRefusal(
                    "LINK_TARGET_MISSING",
                    page,
                    "source page is absent or outside the root",
                    "supply a page inside the documentation root",
                )
            )
            continue
        text = source.read_text(encoding="utf-8")
        for heading in _html_heading_ids(text):
            refusals.append(
                LinkRefusal(
                    "HTML_HEADING_ID",
                    page,
                    f"HTML heading id {heading!r} bypasses the heading algorithm",
                    "use a Markdown heading and its derived id",
                )
            )
        for link in links(text):
            target = f"{page} -> {link.target}"
            try:
                resolved = resolve_link(page, link.target)
            except ValueError as exc:
                refusals.append(
                    LinkRefusal(
                        "LINK_ESCAPES",
                        target,
                        str(exc),
                        "link to a page inside the documentation root",
                    )
                )
                continue
            if resolved.external:
                continue
            destination = root / resolved.path
            if not destination.resolve().is_relative_to(root):
                refusals.append(
                    LinkRefusal(
                        "LINK_ESCAPES",
                        target,
                        "target resolves outside the root",
                        "link to a page inside the documentation root",
                    )
                )
            elif not destination.is_file():
                refusals.append(
                    LinkRefusal(
                        "LINK_TARGET_MISSING",
                        target,
                        "target file is absent",
                        "create the target or correct the relative link",
                    )
                )
            elif resolved.fragment and destination.suffix == ".md":
                ids = heading_ids(destination.read_text(encoding="utf-8"))
                if unquote(resolved.fragment) not in ids:
                    refusals.append(
                        LinkRefusal(
                            "LINK_FRAGMENT_MISSING",
                            target,
                            "fragment does not exactly match a heading id",
                            "use the target page's derived heading id (case-sensitive, percent-decoded once)",
                        )
                    )
    return refusals


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--paths", nargs="+", help="only page paths beginning with these prefixes"
    )
    args = parser.parse_args(argv)
    pages = sorted(p.relative_to(args.root).as_posix() for p in args.root.rglob("*.md"))
    if args.paths:
        pages = [p for p in pages if any(p.startswith(prefix) for prefix in args.paths)]
    refusals = validate_links(args.root, pages)
    for refusal in refusals:
        print(refusal)
    if not refusals:
        print(f"Links OK: {len(pages)} pages")
    return int(bool(refusals))


if __name__ == "__main__":
    raise SystemExit(main())
