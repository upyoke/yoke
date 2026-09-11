"""``yoke strategy render|ingest`` adapters.

The filesystem-facing half of the strategy family (the ``doc *``
adapters live in :mod:`yoke_cli.commands.adapters.strategy`; ``yoke
strategy seed-defaults`` lives in
:mod:`yoke_cli.commands.adapters.strategy_seed_defaults`):

- ``render`` -> ``strategy.render.run`` (fetch the rendered file texts).
- ``ingest`` -> ``strategy.ingest.run`` (CAS write-back of edited files).

File I/O happens HERE, client-side (12942): ``render`` dispatches for
the row→file-text map and writes the files into the checkout it
resolved (``--target-root`` flag, else ``$YOKE_RENDER_TARGET_ROOT``,
else the shared repo-root helper); ``ingest`` reads the rendered files
locally, ships their text in the payload, and writes back the advanced
headers the handler returns. The handlers never touch a filesystem
path, so the same commands work over https against a server with no
checkout. Project context resolves like every strategy command
(``--project`` > ``$YOKE_PROJECT`` > the machine-config
checkout→project map). Once the operation's project is known, both
commands defer to
:mod:`yoke_cli.commands.adapters.strategy_target_project` so a render or
write-back for one project can never land inside a different project's
checkout.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from yoke_cli.commands import _helpers as _helpers
from yoke_cli.commands._helpers import (
    add_json_arg,
    add_project_arg,
    add_session_arg,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.adapters.strategy import (
    resolve_target_root_for_cli,
    strategy_target,
    write_rendered_files,
)
from yoke_cli.commands.adapters.strategy_render_response import (
    compact_file_text_response,
)
from yoke_cli.commands.adapters.strategy_target_project import (
    reject_known_target_root_mismatch,
    resolve_and_validate_target_root,
    target_root_was_explicit,
    StrategyTargetRootMismatchError,
)
from yoke_cli.commands.text_file import resolve_text_file
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher, emit_response
from yoke_contracts.project_contract.strategy_docs_io import (
    StrategyIngestFileMissingError,
    read_ingest_files,
)


__all__ = [
    "strategy_render",
    "strategy_ingest",
    "STRATEGY_RENDER_USAGE",
    "STRATEGY_INGEST_USAGE",
]


STRATEGY_INGEST_USAGE = (
    "yoke strategy ingest [SLUG ...] [--content-file PATH] [--dry-run] "
    "[--target-root PATH] [--project P] [--session-id S] [--json]"
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
            "  yoke strategy ingest MASTER-PLAN             # CAS write-back\n"
            "  # ingest one rendered handoff file from a readable path:\n"
            "  yoke strategy ingest MASTER-PLAN --content-file /tmp/MASTER-PLAN.md"
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
    parser.add_argument(
        "--content-file", dest="content_file", default=None,
        help=(
            "Rendered file for exactly one explicit slug, read from a free "
            "or claim-covered path instead of --target-root."
        ),
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
    explicit_target_root = target_root_was_explicit(parsed.target_root)

    _helpers.ensure_handlers_loaded()
    actor = build_actor(session_id=parsed.session_id)
    target = strategy_target(parsed.project)

    slugs = list(parsed.slugs)
    if parsed.content_file:
        if len(slugs) != 1:
            return usage_error(
                "--content-file requires exactly one explicit SLUG."
            )
        content_path = Path(parsed.content_file).expanduser().resolve()
        try:
            content = resolve_text_file(
                None, str(content_path), "--content-file",
            )
        except ValueError as exc:
            return usage_error(str(exc))
        files = [{
            "slug": slugs[0],
            "path": str(content_path),
            "text": str(content),
        }]
    else:
        # Reading from target_root: resolve project identity and reject a
        # KNOWN mismatch before reading any file or dispatching the
        # mutation — never redirect the read location itself, since the
        # operator's edits live wherever target_root already points.
        identity_response = call_dispatcher(
            function_id="strategy.doc.list", target=target, payload={}, actor=actor,
        )
        if not identity_response.success:
            return emit_response(identity_response, json_mode=parsed.json_mode)
        identity = identity_response.result or {}
        try:
            reject_known_target_root_mismatch(
                target_root,
                project_id=identity.get("project_id"),
                project_slug=identity.get("project_slug"),
            )
        except StrategyTargetRootMismatchError as exc:
            return usage_error(str(exc))

        if not slugs:
            slugs = [str(d["slug"]) for d in identity.get("docs", [])]
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
    render_report = _write_returned_files(
        target_root, response, explicit_target_root=explicit_target_root,
    )

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
        compact_file_text_response(
            response, target_root=target_root, render_report=render_report,
        ),
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )
    return rc


def _write_returned_files(
    target_root, response, *, explicit_target_root: bool = True,
) -> Dict[str, str]:
    """Write any ``file_text`` entries the ingest response carries.

    The written docs already landed in the DB by the time this runs, so a
    project mismatch on ``target_root`` warns and skips the local
    header-advance write rather than unwinding anything.
    """
    result = (response.result or {}) if response else {}
    docs = result.get("docs", [])
    entries = [d for d in docs if d.get("file_text")]
    if not entries:
        return {}
    try:
        target_root = resolve_and_validate_target_root(
            target_root,
            explicit=explicit_target_root,
            project_id=result.get("project_id"),
            project_slug=result.get("project_slug"),
        )
    except StrategyTargetRootMismatchError as exc:
        print(
            "warning: strategy doc(s) ingested in the DB; skipped local "
            f"header refresh — {exc}",
            file=sys.stderr,
        )
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
            "target_root resolves client-side: --target-root, else "
            "$YOKE_RENDER_TARGET_ROOT, else this machine's own registered "
            "checkout for the project (`yoke project register`), else the "
            "repo root (refused from a linked worktree without an "
            "explicit anchor). An explicit --target-root registered to a "
            "DIFFERENT project refuses before writing anything."
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
    explicit_target_root = target_root_was_explicit(parsed.target_root)

    _helpers.ensure_handlers_loaded()
    response = call_dispatcher(
        function_id="strategy.render.run",
        target=strategy_target(parsed.project),
        payload={},
        actor=build_actor(session_id=parsed.session_id),
    )

    report: Optional[Any] = None
    if response.success:
        result = response.result or {}
        try:
            target_root = resolve_and_validate_target_root(
                target_root,
                explicit=explicit_target_root,
                project_id=result.get("project_id"),
                project_slug=result.get("project_slug"),
            )
        except StrategyTargetRootMismatchError as exc:
            return usage_error(str(exc))
        report = write_rendered_files(target_root, result.get("docs", []))

    def _human_writer(human_response, stdout, stderr) -> None:
        for slug, status in (report or {}).items():
            print(f"{slug}\t{status}", file=stdout)

    return emit_response(
        compact_file_text_response(
            response, target_root=target_root, render_report=report,
        ),
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )
