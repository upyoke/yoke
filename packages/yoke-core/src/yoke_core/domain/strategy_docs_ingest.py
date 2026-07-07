"""Compare-and-swap write-back from edited ``.yoke/strategy/`` renders.

The operator's editor bridge behind ``strategy.ingest.run``: edit a
project's tracked rendered ``.yoke/strategy/<slug>.md`` in any editor,
then ingest it back into the DB authority. Lost-update protection is the
header-based compare-and-swap: the UPDATE carries
``WHERE project_id = %s AND slug = %s AND updated_at
= <base-from-header>`` so a row that moved since the file was rendered
refuses the write instead of silently discarding the newer DB content.
Write stamps are microsecond-precision
(:func:`strategy_docs.next_updated_at`) so the CAS token stays unique
even for writes inside the same second.

No process-claim gate here, unlike ``strategy.doc.replace``: the claim
gate coordinates agent strategize/feed flows, while ingest's racing-
writer protection is the CAS itself and file edits stay recoverable in
git either way.

File I/O is the CALLER's: the CLI reads the
rendered files via :func:`read_ingest_files` and ships their text in
the ``strategy.ingest.run`` payload; :func:`plan_ingest` validates the
shipped texts against the DB without touching any filesystem, so the
handler works identically in-process and on a server with no checkout.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from yoke_contracts.project_contract.strategy_docs_io import (
    StrategyIngestFileMissingError,
    read_ingest_files as _read_ingest_files,
)
from yoke_core.domain.strategy_docs import (
    STRATEGY_DOCS_TABLE,
    EmptyStrategyDocError,
    _require_valid_slug,
    get_doc,
    next_updated_at,
)
from yoke_core.domain.strategy_docs_header import (
    StrategyHeaderError,
    content_sha256,
    parse_file_text,
)


@dataclass(frozen=True)
class IngestDocPlan:
    """One doc's validated ingest plan (no writes performed)."""

    slug: str
    path: Path
    base_updated_at: str
    db_updated_at: str
    file_body: str
    changed: bool
    old_lines: int
    new_lines: int
    old_bytes: int
    new_bytes: int

    @property
    def stale_base(self) -> bool:
        return self.base_updated_at != self.db_updated_at


def conflict_teaching(slugs: Sequence[str], target_root: Path) -> str:
    """Canonical recovery teaching for CAS conflicts on the named docs."""
    named = ", ".join(repr(s) for s in slugs)
    rerun = " ".join(slugs)
    return (
        f"strategy doc(s) {named} changed in the DB after the file header(s) "
        "were rendered — refusing the write so the newer DB content is not "
        "lost. Recover: preserve your edited file(s) first (commit them, or "
        "copy them aside), re-render the fresh DB content with `yoke "
        f"strategy render --target-root {target_root}`, then `git diff` the "
        "fresh render against your edited copy and re-apply your edits onto "
        f"the fresh render before re-running `yoke strategy ingest {rerun}`."
    )


def _line_count(text: str) -> int:
    return len(text.splitlines())


def read_ingest_files(
    target_root: Path,
    slugs: Sequence[str],
) -> List[Dict[str, str]]:
    """Read the rendered files for ``slugs``; return ``[{slug, path, text}]``.

    The CALLER-side half of ingest (the CLI adapter runs this on the
    operator checkout before dispatching). Raises
    :class:`StrategyIngestFileMissingError` naming the first absent file
    and teaching the render recovery; header validation stays in
    :func:`plan_ingest` so shipped and local texts validate identically.
    """
    return _read_ingest_files(
        target_root,
        slugs,
        validate_slug=_require_valid_slug,
    )


def plan_ingest(
    conn: Any,
    *,
    project_id: int,
    files: Sequence[Mapping[str, Any]],
) -> List[IngestDocPlan]:
    """Validate every shipped file text and return per-doc plans, writing nothing.

    ``files`` entries are ``{slug, path, text}`` (path is message context
    only — see :func:`read_ingest_files` for the caller-side read).
    Validation precedes mutation: any missing/mangled header, header/slug
    mismatch, missing DB row, or empty changed body refuses the whole run
    before :func:`execute_ingest` writes anything.

    Raises :class:`StrategyHeaderError` (message names the file),
    :class:`yoke_core.domain.strategy_docs.UnknownStrategyDocError`,
    :class:`yoke_core.domain.strategy_docs.StrategyDocMissingError`, or
    :class:`yoke_core.domain.strategy_docs.EmptyStrategyDocError`.
    """
    plans: List[IngestDocPlan] = []
    for entry in files:
        slug = _require_valid_slug(str(entry["slug"]))
        path = Path(str(entry.get("path") or f"{slug}.md"))
        try:
            header = parse_file_text(str(entry["text"]))
        except StrategyHeaderError as exc:
            raise StrategyHeaderError(
                f"{path}: {exc} — ingest only accepts files produced by "
                "`yoke strategy render`; re-render to restore the header.",
                kind=exc.kind,
            ) from exc
        if header.slug != slug:
            raise StrategyHeaderError(
                f"{path}: header names slug {header.slug!r} but the file "
                f"is {slug}.md — re-render to restore the header.",
                kind="mangled",
            )
        row = get_doc(conn, project_id, slug)
        changed = content_sha256(header.body) != header.content_sha256
        if changed and not header.body.strip():
            raise EmptyStrategyDocError(
                f"{path}: refusing to ingest empty content for strategy "
                f"doc {slug!r}; strategy docs are never blanked."
            )
        plans.append(
            IngestDocPlan(
                slug=slug,
                path=path,
                base_updated_at=header.updated_at,
                db_updated_at=row["updated_at"],
                file_body=header.body,
                changed=changed,
                old_lines=_line_count(row["content"]),
                new_lines=_line_count(header.body),
                old_bytes=len(row["content"].encode("utf-8")),
                new_bytes=len(header.body.encode("utf-8")),
            )
        )
    return plans


def _doc_report(plan: IngestDocPlan, status: str, **extra: Any) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "slug": plan.slug,
        "status": status,
        "old_lines": plan.old_lines,
        "new_lines": plan.new_lines,
        "line_delta": plan.new_lines - plan.old_lines,
    }
    report.update(extra)
    return report


def dry_run_report(plans: Sequence[IngestDocPlan]) -> List[Dict[str, Any]]:
    """Per-doc ``changed``/``unchanged``/``conflict`` preview, no writes.

    A changed file whose header base no longer matches the DB row is
    reported as ``conflict`` — the write it previews would CAS-fail.
    """
    report: List[Dict[str, Any]] = []
    for plan in plans:
        if not plan.changed:
            report.append(_doc_report(plan, "unchanged"))
        elif plan.stale_base:
            report.append(
                _doc_report(
                    plan, "conflict",
                    base_updated_at=plan.base_updated_at,
                    db_updated_at=plan.db_updated_at,
                )
            )
        else:
            report.append(_doc_report(plan, "changed"))
    return report


def execute_ingest(
    conn: Any,
    plans: Sequence[IngestDocPlan],
    *,
    project_id: int,
    actor_id: Optional[int],
) -> List[Dict[str, Any]]:
    """Compare-and-swap each changed doc into the DB; return per-doc results.

    Statuses: ``written`` (CAS succeeded; carries ``updated_at``),
    ``unchanged`` (file matches its own header hash — no-op), and
    ``conflict`` (rowcount 0 — the row's ``updated_at`` no longer equals
    the header's base value). Every doc is attempted: docs written
    before a conflict stay written (their headers advance on re-render,
    so a retry after recovery no-ops them).
    """
    results: List[Dict[str, Any]] = []
    for plan in plans:
        if not plan.changed:
            results.append(_doc_report(plan, "unchanged"))
            continue
        new_updated_at = next_updated_at()
        cur = conn.execute(
            f"UPDATE {STRATEGY_DOCS_TABLE} "
            "SET content = %s, updated_at = %s, updated_by_actor_id = %s "
            "WHERE project_id = %s AND slug = %s AND updated_at = %s",
            (
                plan.file_body,
                new_updated_at,
                actor_id,
                project_id,
                plan.slug,
                plan.base_updated_at,
            ),
        )
        if cur.rowcount == 0:
            results.append(
                _doc_report(
                    plan, "conflict",
                    base_updated_at=plan.base_updated_at,
                )
            )
            continue
        conn.commit()
        results.append(
            _doc_report(
                plan, "written",
                updated_at=new_updated_at,
                old_bytes=plan.old_bytes,
                new_bytes=plan.new_bytes,
            )
        )
    return results


__all__ = [
    "IngestDocPlan",
    "StrategyIngestFileMissingError",
    "conflict_teaching",
    "dry_run_report",
    "execute_ingest",
    "plan_ingest",
    "read_ingest_files",
]
