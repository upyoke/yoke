"""Argument parsers for ``yoke qa browser status`` and ``setup``."""

from __future__ import annotations

import argparse

from yoke_contracts.browser_identity import DEFAULT_IDENTITY

QA_BROWSER_STATUS_USAGE = (
    "yoke qa browser status [--project PROJECT] [--identity NAME] [--json]"
)
QA_BROWSER_SETUP_USAGE = (
    "yoke qa browser setup [--dry-run] [--project PROJECT] [--identity NAME] "
    "[--port PORT] [--headed] [--idle-timeout SECONDS] [--json]"
)


def status_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yoke qa browser status",
        usage=QA_BROWSER_STATUS_USAGE,
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Project whose browser to check; default: the current project.",
    )
    parser.add_argument(
        "--identity",
        default=DEFAULT_IDENTITY,
        help="Browser identity whose profile to check; default: %(default)s.",
    )
    parser.add_argument(
        "--json",
        dest="json_mode",
        action="store_true",
        help="Print JSON instead of text.",
    )
    return parser


def setup_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yoke qa browser setup",
        usage=QA_BROWSER_SETUP_USAGE,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report readiness only; install and start nothing.",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Project to set up for; default: the current project.",
    )
    parser.add_argument(
        "--identity",
        default=None,
        help="Declared browser identity whose profile the daemon opens (default: `default`).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port for the browser daemon; default: chosen automatically.",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show the browser window instead of running headless.",
    )
    parser.add_argument(
        "--idle-timeout",
        type=int,
        default=None,
        help="Stop the daemon after this many idle seconds.",
    )
    parser.add_argument(
        "--json",
        dest="json_mode",
        action="store_true",
        help="Print JSON instead of text.",
    )
    return parser
