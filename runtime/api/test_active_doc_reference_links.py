"""Top-level active documentation links resolve to live repository paths."""

from __future__ import annotations

from pathlib import Path
import re


REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def test_top_level_active_document_links_resolve() -> None:
    broken: list[str] = []
    for document in sorted(DOCS.glob("*.md")):
        text = document.read_text(encoding="utf-8")
        for raw_target in MARKDOWN_LINK.findall(text):
            target = raw_target.split("#", 1)[0].strip()
            if not target or "://" in target or target.startswith(("mailto:", "data:")):
                continue
            destination = (document.parent / target).resolve()
            if not destination.exists():
                broken.append(f"{document.relative_to(REPO)} -> {raw_target}")

    assert not broken, "broken active documentation links:\n" + "\n".join(broken)
