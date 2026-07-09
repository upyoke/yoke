"""``yoke strategy render|ingest|seed-defaults`` adapters.

The filesystem-facing half of the strategy family (the ``doc *``
adapters live in :mod:`yoke_cli.commands.adapters.strategy`):

- ``render`` -> ``strategy.render.run`` (fetch the rendered file texts).
- ``ingest`` -> ``strategy.ingest.run`` (CAS write-back of edited files).
- ``seed-defaults`` -> ``strategy.seed_defaults.run`` (cold-start rows).

File I/O happens HERE, client-side (12942): ``render`` dispatches for
the row→file-text map and writes the files into the checkout it
resolved (``--target-root`` flag, else ``$YOKE_RENDER_TARGET_ROOT``,
else the shared repo-root helper); ``ingest`` reads the rendered files
locally, ships their text in the payload, and writes back the advanced
headers the handler returns. The handlers never touch a filesystem
path, so the same commands work over https against a server with no
checkout. Project context resolves like every strategy command
(``--project`` > ``$YOKE_PROJECT`` > the machine-config
checkout→project map).
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Dict, List, Mapping, Optional

from yoke_cli.commands import _helpers as _helpers
from yoke_cli.commands._helpers import (
    add_json_arg,
    add_project_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.adapters.strategy import (
    resolve_target_root_for_cli,
    strategy_target,
    write_rendered_files,
)
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher, emit_response
from yoke_contracts.project_contract.strategy_docs_io import (
    StrategyIngestFileMissingError,
    read_ingest_files,
)
from yoke_contracts.project_contract.strategy_docs_paths import (
    strategy_view_rel_path,
)


__all__ = [
    "strategy_render",
    "strategy_ingest",
    "strategy_seed_defaults",
    "STRATEGY_RENDER_USAGE",
    "STRATEGY_INGEST_USAGE",
    "STRATEGY_SEED_DEFAULTS_USAGE",
]


STRATEGY_INGEST_USAGE = (
    "yoke strategy ingest [SLUG ...] [--dry-run] [--target-root PATH] "
    "[--project P] [--session-id S] [--json]"
)


def strategy_ingest(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke strategy ingest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Write edited rendered strategy files back into the DB "
            "authority via compare-and-swap on each file's render-header "
            "base updated_at (lost-update protection), then re-render the "
            "written docs so their headers advance. Refuses files whose "
            "YOKE:STRATEGY-DOC header is missing or mangled; skips files "
            "whose body still matches the header hash."
        ),
        epilog=(
            "Example:\n"
            "  # edit .yoke/strategy/MASTER-PLAN.md in your editor, then:\n"
            "  yoke strategy ingest MASTER-PLAN --dry-run   # preview\n"
            "  yoke strategy ingest MASTER-PLAN             # CAS write-back"
        ),
    )
    parser.add_argument(
        "slugs", nargs="*", metavar="SLUG",
        help="Doc slugs to ingest; default is the project's full corpus.",
    )
    parser.add_argument(
        "--dry-run", dest="dry_run", action="store_true",
        help="Print per-doc changed/unchanged + line deltas; write nothing.",
    )
    parser.add_argument(
        "--target-root", dest="target_root", default=None,
        help="Checkout root whose rendered .yoke/strategy/ files to read.",
    )
    add_project_arg(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STRATEGY_INGEST_USAGE)
    if parsed is None:
        return 2
    try:
        target_root = resolve_target_root_for_cli(parsed.target_root)
    except RuntimeError as exc:
        return usage_error(str(exc))

    _helpers.ensure_handlers_loaded()
    actor = build_actor(session_id=parsed.session_id)
    target = strategy_target(parsed.project)

    slugs = list(parsed.slugs)
    if not slugs:
        slugs, list_response = _corpus_slugs(target, actor)
        if slugs is None:
            return emit_response(list_response, json_mode=parsed.json_mode)
        if not slugs:
            print(
                "error (doc_not_seeded): the project has no strategy docs; "
                "cold-start with `yoke strategy seed-defaults`.",
                file=sys.stderr,
            )
            return 1

    try:
        files = read_ingest_files(target_root, slugs)
    except StrategyIngestFileMissingError as exc:
        print(f"error (ingest_file_missing): {exc}", file=sys.stderr)
        return 1

    response = call_dispatcher(
        function_id="strategy.ingest.run",
        target=target,
        payload={
            "files": files,
            "dry_run": bool(parsed.dry_run),
            "target_root": str(target_root),
        },
        actor=actor,
    )
    # Advance the written docs' headers on disk whatever the overall
    # outcome — on a partial conflict the docs written before it stay
    # written, and rewriting their headers makes a retry no-op them.
    render_report = _write_returned_files(target_root, response)

    def _human_writer(human_response, stdout, stderr) -> None:
        result = human_response.result or {}
        for doc in result.get("docs", []):
            delta = int(doc.get("line_delta", 0))
            print(
                f"{doc.get('slug')}\t{doc.get('status')}\t"
                f"{doc.get('old_lines')} -> {doc.get('new_lines')} lines "
                f"({'+' if delta >= 0 else ''}{delta})",
                file=stdout,
            )

    rc = emit_response(
        _compact_file_text_response(
            response, target_root=target_root, render_report=render_report,
        ),
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )
    return rc


def _corpus_slugs(target, actor):
    """Resolve the project's full corpus for the no-args ingest default.

    Returns ``(slugs, None)`` on success or ``(None, response)`` carrying
    the failed ``strategy.doc.list`` response for verbatim emission.
    """
    response = call_dispatcher(
        function_id="strategy.doc.list",
        target=target,
        payload={},
        actor=actor,
    )
    if not response.success:
        return None, response
    docs = (response.result or {}).get("docs", [])
    return [str(d["slug"]) for d in docs], None


def _write_returned_files(target_root, response) -> Dict[str, str]:
    """Write any ``file_text`` entries the ingest response carries."""
    docs = ((response.result or {}).get("docs", [])) if response else []
    entries = [d for d in docs if d.get("file_text")]
    if not entries:
        return {}
    return write_rendered_files(target_root, entries)


STRATEGY_RENDER_USAGE = (
    "yoke strategy render [--target-root PATH] [--project P] "
    "[--session-id S] [--json]"
)


def strategy_render(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke strategy render",
        description=(
            "Write the project's gitignored .yoke/strategy/ rendered view "
            "from the DB authority into the local rendered view "
            "(idempotent headers; unchanged content renders byte-identical). "
            "target_root resolves client-side: "
            "--target-root, else $YOKE_RENDER_TARGET_ROOT, else the "
            "repo root (refused from a linked worktree without an "
            "explicit anchor)."
        ),
    )
    parser.add_argument(
        "--target-root", dest="target_root", default=None,
        help="Checkout root receiving the rendered .yoke/strategy/ files.",
    )
    add_project_arg(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STRATEGY_RENDER_USAGE)
    if parsed is None:
        return 2
    try:
        target_root = resolve_target_root_for_cli(parsed.target_root)
    except RuntimeError as exc:
        return usage_error(str(exc))

    _helpers.ensure_handlers_loaded()
    response = call_dispatcher(
        function_id="strategy.render.run",
        target=strategy_target(parsed.project),
        payload={},
        actor=build_actor(session_id=parsed.session_id),
    )

    report: Optional[Any] = None
    if response.success:
        report = write_rendered_files(
            target_root, (response.result or {}).get("docs", []),
        )

    def _human_writer(human_response, stdout, stderr) -> None:
        for slug, status in (report or {}).items():
            print(f"{slug}\t{status}", file=stdout)

    return emit_response(
        _compact_file_text_response(
            response, target_root=target_root, render_report=report,
        ),
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def _line_count(text: str) -> int:
    if not text:
        return 0
    return text.count("\n") if text.endswith("\n") else text.count("\n") + 1


def _compact_doc(
    doc: Mapping[str, Any], render_report: Mapping[str, str],
) -> Dict[str, Any]:
    compact = dict(doc)
    file_text = compact.pop("file_text", None)
    slug = str(compact.get("slug") or "")
    archived = bool(compact.get("archived", False))
    if slug:
        compact["path"] = strategy_view_rel_path(slug, archived=archived)
        if slug in render_report:
            compact["render_status"] = render_report[slug]
    if isinstance(file_text, str):
        compact["file_bytes"] = len(file_text.encode("utf-8"))
        compact["file_lines"] = _line_count(file_text)
    return compact


def _render_counts(render_report: Mapping[str, str]) -> Dict[str, int]:
    return {
        "written": sum(1 for status in render_report.values() if status == "written"),
        "unchanged": sum(
            1 for status in render_report.values() if status == "unchanged"
        ),
    }


def _compact_file_text_response(
    response,
    *,
    target_root,
    render_report: Optional[Mapping[str, str]],
):
    """Return a CLI-facing response with file bodies replaced by metadata."""
    report = dict(render_report or {})
    result = dict(response.result or {})
    docs = result.get("docs")
    if isinstance(docs, list):
        result["docs"] = [
            _compact_doc(doc, report) if isinstance(doc, Mapping) else doc
            for doc in docs
        ]
    result["target_root"] = str(target_root)
    if report:
        result["rendered"] = _render_counts(report)
    return response.model_copy(update={"result": result})


STRATEGY_SEED_DEFAULTS_USAGE = (
    "yoke strategy seed-defaults [--project P] [--session-id S] [--json]"
)


def strategy_seed_defaults(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke strategy seed-defaults",
        description=(
            "Cold-start a project's strategy corpus: mint the default "
            "placeholder rows (MISSION, VISION, MASTER-PLAN, LANDSCAPE) "
            "in the DB authority, parameterized by the project's display "
            "name. Idempotent — a project with ANY existing strategy row "
            "is left untouched. Render files from the rows afterwards "
            "with `yoke strategy render`."
        ),
    )
    add_project_arg(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STRATEGY_SEED_DEFAULTS_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        if result.get("already_seeded"):
            print(
                f"project {result.get('project_slug')} already has "
                f"{result.get('existing_rows')} strategy doc(s); "
                "nothing seeded",
                file=stdout,
            )
            return
        print(
            f"seeded {', '.join(result.get('seeded', []))} for project "
            f"{result.get('project_slug')}",
            file=stdout,
        )

    return dispatch_and_emit(
        function_id="strategy.seed_defaults.run",
        target=strategy_target(parsed.project),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )
