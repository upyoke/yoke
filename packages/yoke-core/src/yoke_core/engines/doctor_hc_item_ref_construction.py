"""HC-item-ref-construction: item-ref prefix literals belong only in the formatter.

A ratchet enforcing the display/internal split for item references:

- DISPLAY is ``{public_item_prefix}-{project_sequence}`` produced only by the
  canonical formatter (``render_item_ref`` / ``format_item_ref``).
- INTERNAL code addresses items by the bare integer ``items.id`` and resolves a
  user token via ``resolve_item_id`` — never by stripping a prefix.

The scanner (``yoke_core.domain.lint_item_ref_construction``) flags any literal
ref-prefix token in Python source outside the formatter/resolver and tests.
Occurrences already present are grandfathered in
``item_ref_construction_baseline.BASELINE``. A listed source file's maintainer
must reduce its allowance whenever that file changes; any NEW or over-baseline
occurrence FAILs so the anti-pattern cannot re-enter the tree.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.item_ref_construction_baseline import BASELINE
from yoke_core.domain.lint_item_ref_construction import (
    counts_by_relpath,
    resolve_project_prefixes,
    scan,
)
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
)

_SLUG = "HC-item-ref-construction"
_TITLE = "Item-ref prefix literals confined to the canonical formatter"


def hc_item_ref_construction(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    repo_root_str = _resolve_repo_root()
    if not repo_root_str:
        rec.record(_SLUG, _TITLE, "PASS", "No repo root resolved — skipping.")
        return

    prefixes = resolve_project_prefixes(conn)
    if not prefixes:
        # Minimal-schema fixtures / no projects: nothing to enforce against.
        rec.record(_SLUG, _TITLE, "SKIP", "No project prefixes resolved.")
        return

    repo_root = Path(repo_root_str)
    hits = scan(repo_root, prefixes)
    counts = counts_by_relpath(repo_root, hits)

    offenders: list[str] = []
    for rel, count in sorted(counts.items()):
        allowed = BASELINE.get(rel, 0)
        if count > allowed:
            offenders.append(rel)

    # Surface stale baseline entries (file cleaned up but still listed) so the
    # map keeps shrinking, but do not fail on them.
    stale = sorted(
        rel for rel, allowed in BASELINE.items() if counts.get(rel, 0) < allowed
    )

    if not offenders:
        detail = ""
        if stale:
            detail = (
                "Baseline can shrink — fewer occurrences than recorded in: "
                + ", ".join(stale)
            )
        rec.record(_SLUG, _TITLE, "PASS", detail)
        return

    offender_lines = []
    hit_by_rel: dict[str, list[str]] = {}
    for hit in hits:
        try:
            rel = hit.path.relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            rel = hit.path.as_posix()
        hit_by_rel.setdefault(rel, []).append(f"{rel}:{hit.line}: {hit.snippet}")
    for rel in offenders:
        allowed = BASELINE.get(rel, 0)
        got = counts[rel]
        offender_lines.append(f"- {rel}: {got} occurrence(s), baseline {allowed}")
        offender_lines.extend(f"    {ln}" for ln in hit_by_rel.get(rel, [])[:5])

    rec.record(
        _SLUG,
        _TITLE,
        "FAIL",
        "New or over-baseline item-ref prefix literals. Use render_item_ref / "
        "format_item_ref for display and resolve_item_id for lookups; never "
        "build or parse a ref inline:\n" + "\n".join(offender_lines),
    )
