"""Shared helpers for the ``yoke`` CLI per-family flag adapters.

Tiny module — extracted from
:mod:`yoke_cli.commands.flag_adapters` so per-family adapter
modules can import the same primitives without forcing the parent
file over the 350-line authored cap. Pure plumbing — no per-family
flag logic lives here.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from typing import Any, Callable, Dict, List, Optional, TextIO

from yoke_contracts.field_note_text import FOOTER as _FIELD_NOTE_FOOTER
from yoke_contracts.api.function_call import TargetRef
from yoke_cli.transport.dispatcher import (
    build_actor,
    call_dispatcher,
    emit_response,
)


__all__ = [
    "ensure_handlers_loaded",
    "add_session_arg",
    "add_json_arg",
    "client_project_context",
    "item_target",
    "resolve_item_id_via_dispatch",
    "parse_or_usage_error",
    "usage_error",
    "dispatch_and_emit",
    "split_comma",
    "attach_field_note_footer",
]


def attach_field_note_footer(parser: argparse.ArgumentParser) -> None:
    """Ensure the field-note footer renders at the end of ``--help``.

    Single-edit lever: every per-subcommand adapter parser flows through
    :func:`parse_or_usage_error`, which calls this helper just before
    ``parser.parse_args`` runs. Argparse renders ``epilog`` at the bottom
    of ``--help`` output, so the footer surfaces on every subcommand's
    ``--help`` block without per-adapter wiring. Idempotent:
    re-attaching when the footer is already on ``epilog`` is a no-op.

    The default ``HelpFormatter`` strips whitespace from ``epilog``; we
    swap to ``RawDescriptionHelpFormatter`` so the multi-line footer's
    line breaks survive the render. Adapters that already pinned a
    formatter (e.g. ``RawTextHelpFormatter``) keep their choice. Parsers
    whose long description already carries the footer are left unchanged
    so their help does not repeat the same directive twice.
    """
    if parser.description and _FIELD_NOTE_FOOTER in parser.description:
        return
    if parser.epilog and _FIELD_NOTE_FOOTER in parser.epilog:
        return
    if parser.epilog:
        parser.epilog = f"{parser.epilog}\n\n{_FIELD_NOTE_FOOTER}"
    else:
        parser.epilog = _FIELD_NOTE_FOOTER
    if parser.formatter_class is argparse.HelpFormatter:
        parser.formatter_class = argparse.RawDescriptionHelpFormatter


def ensure_handlers_loaded() -> None:
    """Register the engine's handlers when in-process dispatch is sanctioned.

    The gate is transport-keyed on the active connection: an https
    connection relays to the server, so no local handlers load; a
    prod-flagged postgres connection is operator-only by doctrine, so
    this pre-load declines it; any other local-postgres connection is
    a local universe whose in-process dispatch is the product path, so
    the engine's handler registry loads. A machine without the engine
    importable degrades to a no-op — the dispatcher then fails closed
    with ``local_postgres_core_unavailable``.
    """
    try:
        from yoke_cli.transport.https import resolve_https_connection

        if resolve_https_connection() is not None:
            return
    except Exception:
        return
    if _active_connection_is_prod_postgres():
        return
    try:
        register = importlib.import_module(
            "yoke_core.domain.handlers.__init_register__"
        )
    except ImportError:
        return
    register.register_all_handlers()


def _active_connection_is_prod_postgres() -> bool:
    """True when the active connection is prod-flagged local postgres.

    Prod postgres stays operator-only: the sanctioned admin surfaces
    drive it explicitly, so this client-side pre-load declines to
    register in-process handlers against it.
    """
    try:
        from yoke_cli.config import machine_config
        from yoke_contracts.machine_config.schema import (
            connection_is_prod,
            POSTGRES_TRANSPORTS,
        )

        connection = machine_config.active_connection()
    except Exception:
        return False
    transport = str(connection.get("transport") or "").strip()
    return transport in POSTGRES_TRANSPORTS and connection_is_prod(connection)


def add_session_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--session-id", default=None,
        help=(
            "Operator-debug override for the ambient session id. Sessions "
            "self-identify automatically (env chain, then the hook-written "
            "process-anchor registry); overrides are recorded on the "
            "dispatched event as session_override."
        ),
    )


def add_json_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--json", dest="json_mode", action="store_true",
        help="Emit the command's JSON response envelope on stdout.",
    )


def add_project_arg(parser: argparse.ArgumentParser) -> None:
    """Explicit project context for project-scoped non-item commands.

    Resolution mirrors :func:`client_project_context`: this flag, then
    ``$YOKE_PROJECT``, then the machine-config checkout→project map
    for the cwd.
    """
    parser.add_argument(
        "--project", default=None,
        help=(
            "Project slug or id (default: the checkout's mapped project "
            "from machine config)."
        ),
    )


def _has_arg(parser: argparse.ArgumentParser, dest: str) -> bool:
    return any(action.dest == dest for action in parser._actions)


def _ensure_project_arg_for_item_parser(parser: argparse.ArgumentParser) -> None:
    if not _has_arg(parser, "item") or _has_arg(parser, "project"):
        return
    parser.add_argument(
        "--project", default=None,
        help="Project context for bare numeric item refs.",
    )


def client_project_context(explicit: Optional[str] = None) -> Optional[str]:
    """Resolve client-local project context for bare numeric item refs.

    Relay contract: this NEVER touches the DB — only the explicit
    ``--project`` flag, the ``YOKE_PROJECT`` env var, and the machine
    config checkout->project map. Session-based inference happens
    server-side in the dispatcher's item-ref resolution
    (:mod:`yoke_core.domain.yoke_function_dispatch_target`).
    """
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    env_project = os.environ.get("YOKE_PROJECT", "").strip()
    if env_project:
        return env_project
    try:
        from yoke_cli.config import machine_config
        from yoke_cli.config.checkout_context import resolve_repo_root_from_cwd

        repo_root = resolve_repo_root_from_cwd()
        if repo_root:
            project_id = machine_config.project_id(repo_root)
            if project_id is not None:
                return str(project_id)
    except Exception:
        return None
    return None


def item_target(
    kind: str,
    raw_ref: Any,
    project: Optional[str] = None,
    **extra: Any,
) -> TargetRef:
    """Build an item-targeted :class:`TargetRef` carrying the raw ref.

    The dispatcher resolves ``item_ref`` server-side, so adapters stay
    DB-free and identical envelopes work over both transports.
    """
    return TargetRef(
        kind=kind,  # type: ignore[arg-type]
        item_ref=str(raw_ref).strip(),
        project_id=client_project_context(project),
        **extra,
    )


def parse_or_usage_error(
    parser: argparse.ArgumentParser, args: List[str], usage: str,
) -> Optional[argparse.Namespace]:
    # Every per-subcommand `--help` carries the field-note footer.
    # The single attach-on-parse hook covers every adapter without per-file
    # editing; argparse renders ``epilog`` at the bottom of the help block.
    _ensure_project_arg_for_item_parser(parser)
    attach_field_note_footer(parser)
    try:
        return parser.parse_args(args)
    except SystemExit as exc:
        # argparse exits 0 for --help / --version and 2 for parse errors.
        # Let --help propagate cleanly; only annotate real parse failures.
        if exc.code == 0:
            raise
        print(f"Usage: {usage}", file=sys.stderr)
        return None


def usage_error(message: str) -> int:
    print(json.dumps({"success": False, "code": "USAGE", "message": message}),
          file=sys.stderr)
    return 2


def dispatch_and_emit(
    *,
    function_id: str,
    target: TargetRef,
    payload: Dict[str, Any],
    session_id: Optional[str],
    json_mode: bool,
    human_writer: Optional[Callable[[Any, TextIO, TextIO], None]] = None,
    local_only: bool = False,
    timeout_s: Optional[float] = None,
    sensitive_values: tuple[str, ...] = (),
) -> int:
    ensure_handlers_loaded()
    actor = build_actor(session_id=session_id)
    response = call_dispatcher(
        function_id=function_id,
        target=target,
        payload=payload,
        actor=actor,
        local_only=local_only,
        timeout_s=timeout_s,
        sensitive_values=sensitive_values,
    )
    return emit_response(
        response, json_mode=json_mode, human_writer=human_writer,
    )


def split_comma(raw: str) -> List[str]:
    return [s.strip() for s in raw.split(",") if s.strip()]


def resolve_item_id_via_dispatch(
    raw_ref: Any,
    project: Optional[str] = None,
    session_id: Optional[str] = None,
) -> int:
    """Resolve a raw item ref to the internal id through the dispatcher.

    For the rare adapter that needs the numeric id client-side (e.g.
    machine-local scratch path namespacing), this rides ``items.get.run``
    over the active transport so resolution authority stays server-side
    on https and in-process locally — never a direct client DB read.
    Raises ``ValueError`` with the server's message on failure.
    """
    ensure_handlers_loaded()
    response = call_dispatcher(
        function_id="items.get.run",
        target=item_target("item", raw_ref, project),
        payload={"fields": ["id"]},
        actor=build_actor(session_id=session_id),
    )
    if not response.success or "item_id" not in (response.result or {}):
        message = (
            response.error.message
            if response.error is not None
            else "item ref resolution failed"
        )
        raise ValueError(message)
    return int(response.result["item_id"])
