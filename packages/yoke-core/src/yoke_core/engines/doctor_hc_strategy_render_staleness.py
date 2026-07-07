"""``HC-strategy-render-staleness`` — rendered strategy views vs DB rows.

For every project checkout this machine knows (the machine-config
checkout→project map), compares each rendered
``.yoke/strategy/<slug>.md`` file's YOKE:STRATEGY-DOC header
(``updated_at`` + ``content_sha256``) against that project's
``strategy_docs`` rows and WARNs naming the stale, missing, headerless,
locally-edited, or row-less (orphan file) docs.

Skip-with-note cases stay green: the ``strategy_docs`` table absent
(pre-cutover validation DBs), no checkouts mapped on this machine, a
mapped checkout missing from disk (doctor may run on a machine that
holds only some projects), or a project with zero strategy rows
(corpus not cold-started yet).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _table_exists,
)

_HC_ID = "strategy-render-staleness"
_HC_DESC = "Rendered .yoke/strategy/ views stale vs strategy_docs DB rows"


def _mapped_checkouts() -> List[Tuple[Path, int]]:
    """Return ``(checkout_root, project_id)`` pairs from machine config."""
    from yoke_core.domain import machine_config
    from yoke_contracts.machine_config.schema import normalize_project_id

    cfg = machine_config.load_config()
    projects = cfg.get("projects", {})
    pairs: List[Tuple[Path, int]] = []
    if isinstance(projects, dict):
        for checkout, entry in sorted(projects.items()):
            if not isinstance(entry, dict):
                continue
            project_id = normalize_project_id(entry.get("project_id"))
            if project_id is None:
                continue
            pairs.append((Path(str(checkout)).expanduser(), project_id))
    return pairs


def _doc_issue(root: Path, slug: str, row: Any) -> "str | None":
    """Return one doc's staleness finding, or None when fresh."""
    from yoke_core.domain.strategy_docs_header import (
        StrategyHeaderError,
        content_sha256,
        parse_file_text,
    )
    from yoke_core.domain.strategy_docs_paths import strategy_view_path

    path = strategy_view_path(root, slug)
    if not path.is_file():
        return (
            f"{slug}: rendered file missing — run `yoke strategy render "
            f"--target-root {root}`"
        )
    try:
        header = parse_file_text(path.read_text(encoding="utf-8"))
    except StrategyHeaderError as exc:
        return (
            f"{slug}: render header {exc.kind} — re-render via `yoke "
            "strategy render` (DB content is unaffected)"
        )
    db_updated_at = str(row["updated_at"])
    if header.updated_at != db_updated_at:
        return (
            f"{slug}: rendered view is stale (header updated_at "
            f"{header.updated_at} <> DB {db_updated_at}) — re-render via "
            "`yoke strategy render`"
        )
    if content_sha256(header.body) != header.content_sha256:
        return (
            f"{slug}: file edited without write-back (body hash <> header "
            "hash) — run `yoke strategy ingest " + slug + "`"
        )
    return None


def _orphan_files(root: Path, known_slugs: set) -> List[str]:
    """Rendered-view files whose slug has no row for the project."""
    from yoke_core.domain.strategy_docs_paths import strategy_dir

    docs_dir = strategy_dir(root)
    if not docs_dir.is_dir():
        return []
    orphans = []
    for path in sorted(docs_dir.glob("*.md")):
        slug = path.stem
        if slug not in known_slugs:
            orphans.append(
                f"{slug}: file {path} has no strategy_docs row for this "
                "project — a project's corpus is its rows; remove the file "
                "or restore the row through a governed path"
            )
    return orphans


def _checkout_issues(
    conn: Any, root: Path, project_id: int, notes: List[str],
) -> List[str]:
    """Collect one mapped checkout's findings (or append a skip note)."""
    from yoke_core.domain.strategy_docs import STRATEGY_DOCS_TABLE

    if not root.is_dir():
        notes.append(f"project {project_id}: checkout {root} not on disk — skipped")
        return []
    rows: Dict[str, Any] = {
        str(r["slug"]): r
        for r in conn.execute(
            f"SELECT slug, updated_at FROM {STRATEGY_DOCS_TABLE} "
            "WHERE project_id = %s",
            (project_id,),
        ).fetchall()
    }
    if not rows:
        notes.append(
            f"project {project_id}: no strategy rows (corpus not "
            "cold-started) — skipped"
        )
        return []
    issues: List[str] = []
    for slug in sorted(rows):
        issue = _doc_issue(root, slug, rows[slug])
        if issue:
            issues.append(f"- [project {project_id} @ {root}] {issue}")
    for orphan in _orphan_files(root, set(rows)):
        issues.append(f"- [project {project_id} @ {root}] {orphan}")
    return issues


def hc_strategy_render_staleness(
    conn: Any, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """WARN on rendered strategy files that drifted from their DB rows."""
    from yoke_core.domain.strategy_docs import STRATEGY_DOCS_TABLE

    if not _table_exists(conn, STRATEGY_DOCS_TABLE):
        rec.record(
            _HC_ID, _HC_DESC, "SKIP",
            f"{STRATEGY_DOCS_TABLE} table missing — strategy-DB substrate "
            "absent on this DB (validation fixture); skipping",
        )
        return
    checkouts = _mapped_checkouts()
    if not checkouts:
        rec.record(
            _HC_ID, _HC_DESC, "SKIP",
            "no checkout→project mappings in machine config — nowhere to "
            "compare rendered strategy views; skipping",
        )
        return
    issues: List[str] = []
    notes: List[str] = []
    checked = 0
    for root, project_id in checkouts:
        found = _checkout_issues(conn, root, project_id, notes)
        if root.is_dir():
            checked += 1
        issues.extend(found)
    if issues:
        if notes:
            issues.extend(f"- (note) {n}" for n in notes)
        rec.record(_HC_ID, _HC_DESC, "WARN", "\n".join(issues))
        return
    note_text = f" ({'; '.join(notes)})" if notes else ""
    rec.record(
        _HC_ID, _HC_DESC, "PASS",
        f"rendered strategy docs match their DB rows across {checked} "
        f"mapped checkout(s){note_text}",
    )


__all__ = ["hc_strategy_render_staleness"]
