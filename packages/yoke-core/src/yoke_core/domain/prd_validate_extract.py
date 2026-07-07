"""Section/item extraction helpers for PRD validation.

Sibling of :mod:`yoke_core.domain.prd_validate`. Owns the predicates that
slice a PRD body into named sections, count list items, and normalize item
references.
"""

from __future__ import annotations

import re


LIST_ITEM_PATTERN = re.compile(r"^[ \t]*([-*]|[0-9]+[.)])", re.MULTILINE)


def has_content(text: str) -> bool:
    return any(line.strip() for line in text.splitlines())


def normalize_item_ref(item_ref: str) -> str:
    stripped = re.sub(r"^[Yy][Oo][Kk]-", "", item_ref)
    stripped = stripped.lstrip("0")
    return stripped or "0"


def _word_match(heading: str, term: str) -> bool:
    lh = heading.lower()
    lt = term.lower()
    pos = lh.find(lt)
    if pos == -1:
        return False
    if pos == 0:
        return True
    before = lh[pos - 1]
    if "a" <= before <= "z":
        return False
    if before == "-" and pos >= 4 and lh[pos - 4:pos - 1] == "non":
        return False
    return True


def extract_section(body: str, name: str) -> str:
    lines = body.splitlines()

    def scan(prefix: str) -> str:
        found = False
        content: list[str] = []
        for line in lines:
            if line.startswith("## "):
                heading = line[3:].strip()
                if prefix == "## ":
                    if found:
                        break
                    if heading == name:
                        found = True
                        continue
                elif found:
                    break
            if line.startswith("### "):
                heading = line[4:].strip()
                if prefix == "### ":
                    if found:
                        break
                    if heading == name:
                        found = True
                        continue
                elif found:
                    break
            if found:
                content.append(line)
        return "\n".join(content)

    exact = scan("## ")
    return exact if exact else scan("### ")


def extract_section_fuzzy(body: str, name: str) -> str:
    lines = body.splitlines()

    def scan(prefix: str) -> str:
        found = False
        content: list[str] = []
        for line in lines:
            if line.startswith("## "):
                heading = line[3:].strip()
                if prefix == "## ":
                    if found:
                        break
                    if _word_match(heading, name):
                        found = True
                        continue
                elif found:
                    break
            if line.startswith("### "):
                heading = line[4:].strip()
                if prefix == "### ":
                    if found:
                        break
                    if _word_match(heading, name):
                        found = True
                        continue
                elif found:
                    content.append(line)
                    continue
            if found:
                content.append(line)
        return "\n".join(content)

    fuzzy = scan("## ")
    return fuzzy if fuzzy else scan("### ")


def count_list_items(text: str) -> int:
    return len(LIST_ITEM_PATTERN.findall(text))
