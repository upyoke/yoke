"""``yoke strategy doc list|get`` adapters + shared strategy-CLI helpers.

Per-project DB-authoritative strategy documents (each project's
``.yoke/strategy/`` files are a gitignored local rendered view, a
regenerated cache):

- ``doc list`` -> ``strategy.doc.list`` (slug/updated_at/bytes table,
  marking archived docs).
- ``doc get`` -> ``strategy.doc.get`` (content to stdout in human mode).

``doc replace``/``doc archive``/``doc unarchive`` live in
:mod:`yoke_cli.commands.adapters.strategy_doc_write`; ``render``/
``ingest`` in :mod:`yoke_cli.commands.adapters.strategy_render`;
``seed-defaults`` in :mod:`yoke_cli.commands.adapters.strategy_seed_defaults`.
Those siblings import ``strategy_target``/``resolve_target_root_for_cli``/
``write_rendered_files`` from here rather than duplicating them.

Project context resolves client-side (``--project`` flag >
``$YOKE_PROJECT`` > the machine-config checkout→project map) and rides
on ``target.project_id``.
"""

from __future__ import annotations

import argparse
from typing import Any, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_project_arg,
    add_session_arg,
    client_project_context,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.project_contract.strategy_docs_io import write_rendered_files
from yoke_contracts.project_contract.workspace_roots import resolve_target_root_for_cli


__all__ = [
    "strategy_doc_list",
    "strategy_doc_get",
    "strategy_target",
    "resolve_target_root_for_cli",
    "write_rendered_files",
    "STRATEGY_DOC_LIST_USAGE",
    "STRATEGY_DOC_GET_USAGE",
]


def strategy_target(project: Any) -> TargetRef:
    """Global-kind target carrying the client-resolved project context."""
    return TargetRef(kind="global", project_id=client_project_context(project))


STRATEGY_DOC_LIST_USAGE = (
    "yoke strategy doc list [--project P] [--session-id S] [--json]"
)


def strategy_doc_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke strategy doc list",
        description=(
            "List the project's DB-authoritative strategy docs (slug, "
            "updated_at, bytes). The repo .yoke/strategy/ directory is "
            "a rendered view."
        ),
    )
    add_project_arg(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STRATEGY_DOC_LIST_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        print(
            f"project {result.get('project_slug')} ({result.get('project_id')})",
            file=stdout,
        )
        for doc in result.get("docs", []):
            marker = "  [archived]" if doc.get("archived") else ""
            print(
                f"{doc.get('slug')}\t{doc.get('updated_by') or '-'}\t"
                f"{doc.get('updated_at')}\t{doc.get('bytes')} bytes{marker}",
                file=stdout,
            )

    return dispatch_and_emit(
        function_id="strategy.doc.list",
        target=strategy_target(parsed.project),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


STRATEGY_DOC_GET_USAGE = (
    "yoke strategy doc get <slug> [--project P] [--session-id S] [--json]"
)


def strategy_doc_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke strategy doc get",
        description=(
            "Print one strategy doc's DB-authoritative content to stdout "
            "(e.g. slug MISSION or MASTER-PLAN) for the project."
        ),
    )
    parser.add_argument("slug", help="Strategy doc slug, e.g. MISSION.")
    add_project_arg(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STRATEGY_DOC_GET_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        stdout.write(str((response.result or {}).get("content", "")))

    return dispatch_and_emit(
        function_id="strategy.doc.get",
        target=strategy_target(parsed.project),
        payload={"slug": parsed.slug},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )
