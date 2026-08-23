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

from yoke_contracts.item_ref import DEFAULT_PUBLIC_ITEM_PREFIX
from yoke_core.domain.item_ref_construction_baseline import baseline_counts
from yoke_core.domain.lint_item_ref_bare_cli_token import (
    scan_bare_internal_cli_token,
)
from yoke_core.domain.lint_item_ref_construction import (
    counts_by_relpath,
    resolve_project_prefixes,
    scan,
    scan_parser_policy,
    stale_parser_policy_allowances,
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
        prefixes = [DEFAULT_PUBLIC_ITEM_PREFIX]

    repo_root = Path(repo_root_str)
    hits = scan(repo_root, prefixes)
    counts = counts_by_relpath(repo_root, hits)
    policy_hits = scan_parser_policy(repo_root)
    stale_policy = stale_parser_policy_allowances(repo_root)
    cli_hits = scan_bare_internal_cli_token(repo_root)

    offenders: list[str] = []
    allowed_counts = baseline_counts()
    for rel, count in sorted(counts.items()):
        allowed = allowed_counts.get(rel, 0)
        if count > allowed:
            offenders.append(rel)

    stale = sorted(
        rel for rel, allowed in allowed_counts.items() if counts.get(rel, 0) < allowed
    )

    if (
        not offenders
        and not stale
        and not policy_hits
        and not stale_policy
        and not cli_hits
    ):
        rec.record(_SLUG, _TITLE, "PASS", "")
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
        allowed = allowed_counts.get(rel, 0)
        got = counts[rel]
        offender_lines.append(f"- {rel}: {got} occurrence(s), baseline {allowed}")
        offender_lines.extend(f"    {ln}" for ln in hit_by_rel.get(rel, [])[:5])
    if stale:
        offender_lines.append("- stale baseline entries: " + ", ".join(stale))
    if stale_policy:
        offender_lines.append(
            "- stale parser-policy allowances: " + ", ".join(stale_policy)
        )
    for hit in policy_hits:
        rel = hit.path.relative_to(repo_root.resolve()).as_posix()
        offender_lines.append(f"- {rel}:{hit.line}: {hit.snippet}")
    for hit in cli_hits:
        rel = hit.path.relative_to(repo_root.resolve()).as_posix()
        offender_lines.append(
            f"- {rel}:{hit.line}: bare-id CLI token: {hit.snippet}"
        )

    rec.record(
        _SLUG,
        _TITLE,
        "FAIL",
        "Item-ref parser policy drift. Use render_item_ref / "
        "format_item_ref for display and resolve_item_id for lookups; never "
        "build or parse a ref inline, and never pass str(item_id) to an "
        "items CLI / sync_done_item boundary:\n" + "\n".join(offender_lines),
    )

# Slug and display name are the ones this check has always reported under.
from yoke_project_checks._declare import (  # noqa: E402
    self_project_checks,
)

PROJECT_HEALTH_CHECKS = self_project_checks(
    ('item-ref-construction', 'Item-ref prefix literals confined to the canonical formatter', hc_item_ref_construction),
)
