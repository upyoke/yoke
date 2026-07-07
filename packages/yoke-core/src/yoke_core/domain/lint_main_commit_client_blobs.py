"""Compare client-provided strategy blob summaries against DB rows."""

from __future__ import annotations

from typing import Mapping, Optional, Tuple


def client_blob_freshness_finding(
    rows: Mapping[str, Tuple[str, str]],
    slug: str,
    blob_fact: Optional[Mapping[str, object]],
) -> Optional[str]:
    """Classify one client-provided strategy blob summary against its row."""
    from yoke_core.domain.strategy_docs_header import content_sha256

    if blob_fact is None:
        return f"{slug}: client blob facts missing — cannot verify against the DB row"
    if blob_fact.get("blob_unreadable") is True:
        return f"{slug}: blob unreadable — cannot verify against the DB row"
    header_error = blob_fact.get("header_error")
    if isinstance(header_error, str) and header_error:
        return (
            f"{slug}: render header {header_error} — only `yoke strategy "
            "render` output is committable"
        )
    row = rows.get(slug)
    if row is None:
        return (
            f"{slug}: no strategy_docs row for this project — a project's "
            "corpus is its rows; remove the file or restore the row through "
            "a governed path"
        )
    header_slug = blob_fact.get("header_slug")
    header_updated_at = blob_fact.get("header_updated_at")
    header_sha = blob_fact.get("header_content_sha256")
    body_sha = blob_fact.get("body_sha256")
    db_updated_at, db_content = row
    if header_slug != slug:
        return f"{slug}: header names slug {header_slug!r} — re-render"
    if header_updated_at != db_updated_at:
        return (
            f"{slug}: stale render (header updated_at {header_updated_at} "
            f"<> DB {db_updated_at}) — re-render via `yoke strategy render`"
        )
    if body_sha != header_sha:
        return (
            f"{slug}: edited without write-back (body hash <> header hash) "
            f"— run `yoke strategy ingest {slug}`"
        )
    if body_sha != content_sha256(db_content):
        return (
            f"{slug}: body does not match the DB row content — re-render "
            "via `yoke strategy render`"
        )
    return None


__all__ = ["client_blob_freshness_finding"]
