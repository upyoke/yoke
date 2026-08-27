"""Scanner: bare internal ids must not cross an item-ref CLI boundary.

A Python ``int`` is ``items.id``. A digit *string* passed to ``items get`` /
``items update`` / ``sync_done_item`` / ``run_scan`` is a project-local
public sequence under the default project (``allow_bare_internal=False``).
That swap is how a deploy stamp printed success while writing no row — or
the wrong row — for a non-default-project item, and how the done
transition's discovery scan refused every item whose internal id was not
also a live public sequence.

:func:`scan_bare_internal_cli_token` flags the construction shapes that
reintroduce the swap. The match runs over whole file text rather than a
single line, because the shape that shipped the discovery-scan defect wrote
the argument on the line after the call opened. Tests are exempt (same
policy as the sibling ref-construction scanner). There is no allowance
list: after the pipeline callers address items by integer
``target.item_id``, production source should have zero hits.
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


#: Functions whose leading positional argument is an operator-facing item
#: reference, resolved with ``allow_bare_internal=False``.
_ITEM_REF_BOUNDARIES = ("sync_done_item", "sync_body", "run_scan")

_BARE_CLI_TOKEN_RE = re.compile(
    r"""
    (?:
        _yoke_db\(\s*['"]items['"]\s*,\s*['"](?:get|update)['"]\s*,
            \s*(?:str\()?item_id\b
        |['"]items['"]\s*,\s*['"](?:get|update)['"]\s*,\s*(?:str\()?item_id\b
        |(?:"""
    + "|".join(_ITEM_REF_BOUNDARIES)
    + r""")\(\s*str\(\s*item_id\b
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
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for match in _BARE_CLI_TOKEN_RE.finditer(source):
                lineno = source.count("\n", 0, match.start()) + 1
                hits.append(
                    RefLiteralHit(
                        path=path.resolve(),
                        line=lineno,
                        snippet=" ".join(match.group(0).split())[:160],
                    )
                )
    return hits


__all__ = ["scan_bare_internal_cli_token"]
