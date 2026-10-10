"""Split reflection text at declared headers and optional end markers."""

from __future__ import annotations

import re
from typing import List, Optional


def _split_by_header(
    block: str,
    header_re: re.Pattern,
    end_re: Optional[re.Pattern],
) -> List[str]:
    """Split a block into entry segments by header (and optional end-marker) lines."""
    starts = [m.start() for m in header_re.finditer(block)]
    if not starts:
        return []
    segments: list[str] = []
    for i, start in enumerate(starts):
        next_start = starts[i + 1] if i + 1 < len(starts) else len(block)
        seg = block[start:next_start]
        if end_re is not None:
            end_match = end_re.search(seg)
            if end_match:
                seg = seg[: end_match.start()]
        seg_lines = seg.split("\n")
        if seg_lines:
            seg = "\n".join(seg_lines[1:])
        segments.append(seg.strip())
    return segments
