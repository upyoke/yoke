"""Scanner: bare internal ids must not cross an item-ref CLI boundary.

A Python ``int`` is ``items.id``. A digit *string* passed to ``items get`` /
``items update`` / ``sync_done_item`` is a project-local public sequence
under the default project (``allow_bare_internal=False``). That swap is
how a deploy stamp printed success while writing no row — or the wrong
row — for a non-default-project item.

:func:`scan_bare_internal_cli_token` flags the construction shapes that
reintroduce the swap. Tests are exempt (same policy as the sibling
ref-construction scanner). There is no allowance list: after the pipeline
callers address items by integer ``target.item_id``, production source
should have zero hits.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List

from yoke_core.domain.lint_item_ref_construction import (
    RefLiteralHit,
    _SCAN_ROOTS,
    _is_exempt,
)


_BARE_CLI_TOKEN_RE = re.compile(
    r"""
    (?:
        _yoke_db\(\s*['"]items['"]\s*,\s*['"](?:get|update)['"]\s*,
            \s*(?:str\()?item_id\b
        |['"]items['"]\s*,\s*['"](?:get|update)['"]\s*,\s*(?:str\()?item_id\b
        |sync_done_item\(\s*str\(\s*item_id\b
    )
    """,
    re.VERBOSE,
)


def scan_bare_internal_cli_token(repo_root: Path) -> List[RefLiteralHit]:
    """Return every bare-id-as-item-ref CLI construction in shippable source."""
    root = repo_root.resolve()
    hits: List[RefLiteralHit] = []
    for scan_root in _SCAN_ROOTS:
        base = root / scan_root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            try:
                rel = path.resolve().relative_to(root).as_posix()
            except ValueError:
                continue
            if _is_exempt(rel):
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for lineno, raw in enumerate(lines, start=1):
                if _BARE_CLI_TOKEN_RE.search(raw):
                    hits.append(
                        RefLiteralHit(
                            path=path.resolve(),
                            line=lineno,
                            snippet=raw.strip()[:160],
                        )
                    )
    return hits


__all__ = ["scan_bare_internal_cli_token"]
