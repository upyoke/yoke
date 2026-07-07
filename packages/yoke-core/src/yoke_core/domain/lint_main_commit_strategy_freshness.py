"""First-class strategy rendered-view freshness deny (per staged file).

Two enforcement points share this module's blob classification:

* the PreToolUse commit lint (:mod:`lint_main_commit`) DENIES a
  main-branch ``git commit`` when ANY staged ``.yoke/strategy/*.md``
  view fails the header/updated_at/sha match against its per-project
  ``strategy_docs`` row — evaluated BEFORE the ``# lint:no-main-check``
  suppression (so suppressing the impl-on-main rule no longer bypasses
  freshness as collateral), independent of in-flight worktree items,
  per staged file (mixed commits included), with its own separately
  audited override token;
* the merge preflight (the strategy-view freshness check in
  :mod:`yoke_core.engines.merge_worktree_prepare_preflight`) refuses
  a branch whose incoming strategy views differ from the merge target
  and fail the same freshness match — ``git merge`` never enters the
  commit lint, so drift on a branch would otherwise ride the merge to
  main unchecked.

The authoritative rows resolve through the dispatcher — ONE
``strategy.render.run`` call carrying every staged slug — which rides
the active transport (in-process dispatch under local-postgres, the
https relay otherwise), so both protections behave identically on
DB-attached and https-only machines. Never a direct client DB read.

Fail-closed, narrowly: an unmapped checkout, a dispatcher refusal, or
a transport failure blocks ONLY when strategy views are actually in
play — a strategy-file commit/merge that cannot be verified is refused
(the denial names the failure, the local-postgres retry, and the
audited override); commits and merges that touch no strategy views are
never blocked by this rule.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from yoke_contracts.hook_runner.main_commit import STRATEGY_FRESHNESS_SUPPRESSION
from yoke_core.domain.lint_main_commit_client_blobs import (
    client_blob_freshness_finding,
)

SUPPRESSION_TOKEN = STRATEGY_FRESHNESS_SUPPRESSION

# Ceiling for the https relay leg of the row fetch. The lint runs inside
# the PreToolUse chain's shared deadline (hook_runner_total_timeout_ms,
# default 3000ms), so the single batched round trip must return — or
# fail closed — well within it. In-process dispatch ignores this knob.
DISPATCH_TIMEOUT_S = 2.0


def _local_postgres_retry() -> str:
    """Name the machine's local-postgres retry env for failure messages."""
    try:
        from yoke_core.domain.machine_config import load_config
        from yoke_contracts.machine_config.schema import (
            ENV_OVERRIDE,
            local_postgres_envs,
        )

        envs = local_postgres_envs(load_config())
    except Exception:
        envs = []
    if envs:
        return (
            f"retry under a local-postgres env: {ENV_OVERRIDE}={envs[0]} "
            f"<command> (configured: {', '.join(envs)})"
        )
    return (
        "no local-postgres env is configured on this machine "
        "(see `yoke config example`)"
    )


def _rows_unavailable_finding(detail: str) -> str:
    """Fail-closed finding when the authoritative rows cannot be resolved."""
    return (
        "the strategy_docs rows could not be resolved over the active "
        f"transport ({detail}) — failing closed for strategy-view changes; "
        f"{_local_postgres_retry()}"
    )


def load_project_strategy_rows(
    project_ctx: object,
    slugs: Iterable[str],
    *,
    rows_cache: Optional[dict] = None,
) -> Tuple[Optional[Dict[str, Tuple[str, str]]], Optional[str]]:
    """Resolve ``{slug: (updated_at, content)}`` rows via the dispatcher.

    ONE ``strategy.render.run`` call carries every requested slug and
    rides the active transport, so the same code path serves DB-attached
    machines (in-process dispatch) and https-only machines (the relay).
    ``project_ctx`` is the client project context (numeric id or slug)
    that rides on ``target.project_id``; the server resolves it.

    Returns ``(rows, None)`` on success and ``(None, detail)`` on any
    failure — *detail* names the dispatcher/transport cause for the
    fail-closed denial. ``rows_cache`` is a same-evaluation memo dict:
    the freshness deny and the matches-the-master authorization both run
    on one commit, and the memo dedupes the (potentially large) fetch.
    """
    wanted = tuple(sorted({str(s) for s in slugs if s}))
    if not wanted:
        return {}, None
    key = (str(project_ctx), wanted)
    if rows_cache is not None and key in rows_cache:
        return rows_cache[key]
    result = _load_rows_via_dispatch(key[0], wanted)
    if rows_cache is not None:
        rows_cache[key] = result
    return result


def _load_rows_via_dispatch(
    project_ctx: str, slugs: Tuple[str, ...],
) -> Tuple[Optional[Dict[str, Tuple[str, str]]], Optional[str]]:
    """Dispatch one bounded ``strategy.render.run`` and parse rows back."""
    try:
        from yoke_core.domain.strategy_docs_header import parse_file_text
        from yoke_contracts.api.function_call import TargetRef
        from yoke_core.api.service_client_structured_api_adapter import (
            build_actor,
            call_dispatcher,
        )

        response = call_dispatcher(
            function_id="strategy.render.run",
            target=TargetRef(kind="global", project_id=project_ctx),
            payload={"slugs": list(slugs)},
            actor=build_actor(),
            timeout_s=DISPATCH_TIMEOUT_S,
        )
    except Exception as exc:
        return None, (
            "strategy.render.run dispatch raised "
            f"{exc.__class__.__name__}: {exc}"
        )
    if not response.success:
        error = response.error
        code = error.code if error is not None else "unknown_error"
        message = error.message if error is not None else "no detail"
        return None, f"strategy.render.run refused ({code}): {message}"
    rows: Dict[str, Tuple[str, str]] = {}
    for doc in (response.result or {}).get("docs", []):
        slug = str(doc.get("slug") or "")
        try:
            header = parse_file_text(str(doc.get("file_text") or ""))
        except Exception as exc:
            return None, (
                f"rendered doc {slug!r} did not round-trip the strategy "
                f"header ({exc}) — refusing to compare against it"
            )
        rows[slug] = (str(doc.get("updated_at") or ""), header.body)
    return rows, None


def blob_freshness_finding(
    rows: Dict[str, Tuple[str, str]], slug: str, blob_text: Optional[str],
) -> Optional[str]:
    """Classify one rendered-view blob against its row; None when fresh."""
    from yoke_core.domain.strategy_docs_header import (
        StrategyHeaderError,
        content_sha256,
        parse_file_text,
    )

    if blob_text is None:
        return f"{slug}: blob unreadable — cannot verify against the DB row"
    row = rows.get(slug)
    if row is None:
        return (
            f"{slug}: no strategy_docs row for this project — a project's "
            "corpus is its rows; remove the file or restore the row through "
            "a governed path"
        )
    try:
        header = parse_file_text(blob_text)
    except StrategyHeaderError as exc:
        return (
            f"{slug}: render header {exc.kind} — only `yoke strategy "
            "render` output is committable"
        )
    db_updated_at, db_content = row
    if header.slug != slug:
        return f"{slug}: header names slug {header.slug!r} — re-render"
    if header.updated_at != db_updated_at:
        return (
            f"{slug}: stale render (header updated_at {header.updated_at} "
            f"<> DB {db_updated_at}) — re-render via `yoke strategy render`"
        )
    if content_sha256(header.body) != header.content_sha256:
        return (
            f"{slug}: edited without write-back (body hash <> header hash) "
            f"— run `yoke strategy ingest {slug}`"
        )
    if content_sha256(header.body) != content_sha256(db_content):
        return (
            f"{slug}: body does not match the DB row content — re-render "
            "via `yoke strategy render`"
        )
    return None


def staged_strategy_freshness_findings(
    staged: Sequence[str],
    *,
    worktree_content_paths: frozenset = frozenset(),
    rows_cache: Optional[dict] = None,
    project_ctx: Optional[str] = None,
    client_strategy_blobs: Optional[Mapping[str, Mapping[str, object]]] = None,
) -> Optional[List[str]]:
    """Per-file findings for STAGED strategy views, or ``None`` when none staged.

    Returns ``[]`` when every staged strategy view is fresh. Reads
    staged blobs (``git show :<path>``) — the commit ships the index,
    not the working tree — EXCEPT for ``worktree_content_paths`` members
    (same-command ``git add`` targets): the pending add
    overwrites the index entry, so those verify the worktree file the
    commit will actually ship.
    """
    from yoke_core.domain.lint_main_commit_process_claims import (
        _commit_repo_project_context,
        _staged_blob,
    )
    from yoke_core.domain.lint_staged_union import worktree_blob
    from yoke_core.domain.strategy_docs_paths import slug_from_view_path

    slugs_by_path = {
        path: slug_from_view_path(path)
        for path in staged
        if slug_from_view_path(path) is not None
    }
    if not slugs_by_path:
        return None
    resolved_project = project_ctx or _commit_repo_project_context()
    if resolved_project is None:
        return [
            _rows_unavailable_finding(
                "this checkout maps to no project — $YOKE_PROJECT is "
                "unset and the machine-config checkout map has no entry "
                "for it"
            )
        ]
    rows, failure = load_project_strategy_rows(
        resolved_project, slugs_by_path.values(), rows_cache=rows_cache,
    )
    if rows is None:
        return [_rows_unavailable_finding(failure or "unknown failure")]
    findings: List[str] = []
    for path, slug in sorted(slugs_by_path.items()):
        if client_strategy_blobs is not None:
            finding = client_blob_freshness_finding(
                rows, slug, client_strategy_blobs.get(path),
            )
        else:
            blob = (
                worktree_blob(path)
                if path in worktree_content_paths
                else _staged_blob(path)
            )
            finding = blob_freshness_finding(rows, slug, blob)
        if finding:
            findings.append(finding)
    return findings


def staged_freshness_denial(
    staged: Sequence[str],
    *,
    worktree_content_paths: frozenset = frozenset(),
    rows_cache: Optional[dict] = None,
    project_ctx: Optional[str] = None,
    client_strategy_blobs: Optional[Mapping[str, Mapping[str, object]]] = None,
) -> Optional[str]:
    """Denial reason for a main-branch commit with stale strategy views."""
    findings = staged_strategy_freshness_findings(
        staged,
        worktree_content_paths=worktree_content_paths,
        rows_cache=rows_cache,
        project_ctx=project_ctx,
        client_strategy_blobs=client_strategy_blobs,
    )
    if not findings:
        return None
    from yoke_core.domain.denial_field_note_footer import (
        append_field_note_footer,
    )

    listed = "\n  ".join(findings)
    body = (
        "BLOCKED: stale strategy rendered view staged for commit on main.\n\n"
        f"  {listed}\n\n"
        "The Yoke DB is authoritative for strategy docs; a committed "
        ".yoke/strategy/ view must byte-match its strategy_docs row.\n\n"
        "Recover:\n"
        "  1. Un-ingested file edit -> write it back AND commit in one step:\n"
        "     yoke strategy ingest <SLUG> --commit \"<msg>\"\n"
        "     (ingest re-renders, then stages + commits the fresh views). Or run\n"
        "     `yoke strategy ingest <SLUG>` as its OWN command, THEN git add +\n"
        "     commit -- do NOT pipe ingest into the commit chain: a\n"
        "     `... | tail && git commit` masks ingest's exit, so the commit\n"
        "     stages a pre-write-back view and trips this gate.\n"
        "  2. Stale render (DB moved on) -> yoke strategy render "
        "--target-root <repo-root>\n"
        "  3. Ingest bounced by a live strategize/feed claim -> wait for "
        "that session,\n"
        "     re-render, re-apply your edit, ingest again.\n\n"
        f"Override: add {SUPPRESSION_TOKEN} to the command (audited "
        "separately from # lint:no-main-check)."
    )
    return append_field_note_footer(
        body, rule_id="lint-main-commit-strategy-freshness",
    )


__all__ = [
    "DISPATCH_TIMEOUT_S",
    "SUPPRESSION_TOKEN",
    "blob_freshness_finding",
    "client_blob_freshness_finding",
    "load_project_strategy_rows",
    "staged_freshness_denial",
    "staged_strategy_freshness_findings",
]
