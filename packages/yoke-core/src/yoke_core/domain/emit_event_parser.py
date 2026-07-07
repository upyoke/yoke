"""Argument parser construction for the emit_event CLI surface.

Hosts the custom :class:`EmitEventArgumentParser` (which raises
:class:`UsageError` instead of calling :func:`sys.exit`), the
``VALID_EVENT_KINDS`` tuple, and the :func:`build_parser` factory consumed
by :func:`yoke_core.domain.emit_event.main`.

The parser pulls ``VALID_SOURCE_TYPES`` and ``VALID_SEVERITIES`` from
:mod:`yoke_core.domain.events_crud` so any future change to those
choices is tracked automatically.
"""

from __future__ import annotations

import argparse

from yoke_core.domain import events_crud


VALID_EVENT_KINDS = (
    "analytics",
    "system",
    "audit",
    "security",
    "metric",
    "lifecycle",
    "workflow",
)


class UsageError(Exception):
    """Raised when CLI arguments do not match the contract."""


class EmitEventArgumentParser(argparse.ArgumentParser):
    """Parser with shell-compatible error handling."""

    def error(self, message: str) -> None:  # pragma: no cover - exercised via main()
        raise UsageError(message)


def build_parser() -> EmitEventArgumentParser:
    parser = EmitEventArgumentParser(
        prog="python3 -m yoke_core.domain.emit_event",
        add_help=True,
    )
    parser.add_argument("--name")
    parser.add_argument("--kind", choices=VALID_EVENT_KINDS)
    parser.add_argument("--type")
    parser.add_argument("--source-type", choices=events_crud.VALID_SOURCE_TYPES)
    parser.add_argument("--severity", choices=events_crud.VALID_SEVERITIES, default="INFO")
    parser.add_argument("--outcome", default="")
    parser.add_argument("--session-id", default="")
    parser.add_argument("--event-id", default="")
    parser.add_argument("--user-id", default="")
    parser.add_argument("--org-id", default="")
    parser.add_argument("--request-id", default="")
    parser.add_argument("--actor-id", type=int)
    parser.add_argument("--environment", default="")
    parser.add_argument("--service", default="cli")
    parser.add_argument("--project", default="")
    parser.add_argument("--item-id", default="")
    parser.add_argument("--task-num", type=int)
    parser.add_argument("--agent", default="")
    parser.add_argument("--tool-name", default="")
    parser.add_argument("--duration-ms", type=int)
    parser.add_argument("--exit-code", type=int)
    parser.add_argument("--trace-id", default="")
    parser.add_argument("--parent-id", default="")
    parser.add_argument("--anomaly-flags", default="")
    parser.add_argument("--tool-use-id", default="")
    parser.add_argument("--turn-id", default="")
    parser.add_argument("--hook-event-name", default="")
    parser.add_argument("--context", default="")
    parser.add_argument("--error-context", default="")
    return parser
