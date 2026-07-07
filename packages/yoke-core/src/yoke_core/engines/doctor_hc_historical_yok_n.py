"""HC-historical-yok-n-cruft: flag historical YOK-N references in live prose.

Delegates to :mod:`yoke_core.domain.lint_yok_n_cruft`. Ships at
``severity=warn`` for the first release so the first sweep result surfaces
without blocking unrelated work. Future releases may tighten to FAIL
once the live-surface tree settles at zero.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.lint_yok_n_cruft import scan
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
)

# ---------------------------------------------------------------------------
# Generated-output exemption
# ---------------------------------------------------------------------------
#
# The scanner core (``yoke_core.domain.lint_yok_n_cruft_scan``) already
# strips knowledge-layer and archive trees up front via its
# ``_EXEMPT_PATH_SEGMENTS`` tuple — notably any ``archive`` segment, so
# ``docs/archive/**`` decision records never reach this HC. What it does NOT
# strip are *generated outputs* whose YOK-N tokens are rendered or snapshot
# content rather than authored historical provenance. Flagging those is pure
# noise: the reference cannot be fixed in place (it is regenerated from a
# source the scan covers separately), so every doctor run re-surfaces it and
# the operator must re-reason "my change added no new cruft" to dismiss the
# WARN — the signal-to-noise loss this exemption removes.
#
# We suppress those findings at the HC record layer, the same shape
# ``HC-architecture-*`` uses: it scans broadly and then drops findings on
# paths carrying an exemption family
# (``doctor_hc_architecture.path_in_exemption_family``; families
# ``architecture_generated`` / ``architecture_archive`` in
# ``yoke_core.domain.path_context``). Those families are DB-registry-driven
# (one ``path_context_values`` row per registered ``path_targets`` id) and are
# not populated for these filesystem trees, so we mirror the *intent* with a
# local repo-relative root allowlist rather than the registry surface.
_GENERATED_OUTPUT_ROOTS: tuple[str, ...] = (
    # Archived evidence + spec-history snapshots: point-in-time generated
    # artifacts, not live teaching prose.
    "docs/archive/legacy-plan-artifacts",
    # Harness agent adapters rendered from the canonical bodies under
    # ``runtime/agents/`` by ``agents.render``. Their YOK-N tokens are rendered
    # packet example ids; authored agent-prose cruft is still caught at the
    # canonical source, which the scan covers independently.
    "runtime/harness/claude/agents",
    "runtime/harness/codex/agents",
)


def _is_generated_output_path(rel_posix: str) -> bool:
    """Return True when *rel_posix* (a repo-relative POSIX path) lives under a
    generated-output root the cruft policy exempts."""
    return any(
        rel_posix == root or rel_posix.startswith(f"{root}/")
        for root in _GENERATED_OUTPUT_ROOTS
    )


def hc_historical_yok_n_cruft(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-historical-yok-n-cruft: historical YOK-N provenance in live prose."""
    repo_root_str = _resolve_repo_root()
    if not repo_root_str:
        rec.record(
            "HC-historical-yok-n-cruft",
            "Historical YOK-N references in live prose",
            "PASS",
            "No repo root resolved — skipping.",
        )
        return
    repo_root = Path(repo_root_str)
    repo_root_resolved = repo_root.resolve()

    db_path = getattr(args, "db_path", None)
    result = scan(repo_root, db_path=db_path)

    # Drop hits under generated-output trees (see ``_GENERATED_OUTPUT_ROOTS``):
    # rendered/snapshot YOK-N tokens are not authored provenance, and their
    # source surfaces are scanned independently. Live tracked-source cruft —
    # the HC's real job — is retained.
    live_hits = []
    for hit in result.hits:
        try:
            rel = hit.path.resolve().relative_to(repo_root_resolved)
        except ValueError:
            live_hits.append(hit)
            continue
        if _is_generated_output_path(rel.as_posix()):
            continue
        live_hits.append(hit)

    if not live_hits:
        rec.record(
            "HC-historical-yok-n-cruft",
            "Historical YOK-N references in live prose",
            "PASS",
            "",
        )
        return

    lines = []
    for hit in live_hits[:40]:
        try:
            rel = hit.path.resolve().relative_to(repo_root_resolved)
        except ValueError:
            rel = hit.path
        lines.append(f"- {rel}:{hit.line}: {hit.ticket} (status={hit.status}) — {hit.context[:120]}")
    extra = ""
    if len(live_hits) > 40:
        extra = f"\n- … {len(live_hits) - 40} more references (run `python3 -m yoke_core.domain.lint_yok_n_cruft` for the full list)."
    rec.record(
        "HC-historical-yok-n-cruft",
        "Historical YOK-N references in live prose",
        "WARN",
        "\n".join(lines) + extra,
    )
