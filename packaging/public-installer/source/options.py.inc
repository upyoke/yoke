#!/usr/bin/env python3
"""Install the Yoke product CLI from Yoke's private package index."""

from __future__ import annotations

import argparse
import glob
import fcntl
import json
import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BASE_URL = "https://api.upyoke.com"
DEFAULT_CHANNEL = "stable"
# Immutable per-release record the distribution publishes beside its wheels.
# Same path as yoke_core.tools.release_artifacts; this bootstrap installer
# cannot import installed yoke-core just to share that helper.
_RELEASE_RECORD_DIR = "dist/releases"
_RELEASE_RECORD_FILENAME = "release-records.json"
GUTTER_ICON = "☀"
PLAIN_GUTTER_ICON = "*"
# Every Yoke-emitted setup line wears this amber-sun gutter so it stands out
# from any uv output that scrolls past. Colorized when the terminal supports it
# (see Installer._resolve_color).
GUTTER = GUTTER_ICON

# Truecolor SGR sequences require an explicit terminal capability.
_SGR_CODES = {
    "brand": "1;38;2;63;185;80",  # bold accent #3fb950
    "bright": "38;2;86;211;100",  # accent-bright #56d364
    "dim": "38;2;125;133;144",  # dim #7d8590
    "danger": "1;38;2;248;81;73",  # bold danger #f85149
    "amber": "38;2;210;153;34",  # amber #d29922 (the sun)
}

_ANSI_CODES = {
    "brand": "1;32",
    "bright": "32",
    "dim": "39",
    "danger": "1;31",
    "amber": "33",
}


def _paint(text: str, key: str, *, enabled: bool) -> str:
    if not enabled:
        return text
    codes = _SGR_CODES if os.environ.get("COLORTERM") in {"truecolor", "24bit"} else _ANSI_CODES
    return f"\033[{codes[key]}m{text}\033[0m"


_DEV_VERSION_RE = re.compile(r"^(?P<base>\d+\.\d+(?:\.\d+)?)\.dev\d+\+(?P<local>.+)$")
PRODUCT_PACKAGE = "yoke-cli"
LOCKSTEP_PRODUCT_PACKAGES = ("yoke-contracts", "yoke-harness", "yoke-core")
# Inclusive endpoints: CI reads this declaration without importing the helper.
SUPPORTED_PYTHON = ((3, 11), (3, 14))
PYTHON_CONSTRAINT = (
    f">={SUPPORTED_PYTHON[0][0]}.{SUPPORTED_PYTHON[0][1]},"
    f"<{SUPPORTED_PYTHON[1][0]}.{SUPPORTED_PYTHON[1][1] + 1}"
)
PYPI_INDEX_URL = "https://pypi.org/simple/"
INDEX_STRATEGY = "first-index"
# The public installer owns resolver sources completely. Ambient uv index
# settings must not replace PyPI or insert a higher-priority index ahead of the
# Yoke index selected by the installer.
UV_INDEX_ENV_VARS = frozenset(
    {
        "UV_DEFAULT_INDEX",
        "UV_EXTRA_INDEX_URL",
        "UV_INDEX",
        "UV_INDEX_STRATEGY",
        "UV_INDEX_URL",
        "UV_NO_INDEX",
    }
)
# Requirement/override/find-links inputs can inject packages independently of
# indexes.  The public installer pins the complete lockstep product set, so it
# deliberately inherits none of these ambient resolver source surfaces.
UV_REQUIREMENT_SOURCE_ENV_VARS = frozenset(
    {
        "UV_BUILD_CONSTRAINT",
        "UV_CONFIG_FILE",
        "UV_CONSTRAINT",
        "UV_FIND_LINKS",
        "UV_OVERRIDE",
        "UV_REQUIREMENT",
    }
)
PIP_REQUIREMENT_SOURCE_ENV_VARS = frozenset(
    {
        "PIP_CONSTRAINT",
        "PIP_EXTRA_INDEX_URL",
        "PIP_FIND_LINKS",
        "PIP_INDEX_URL",
        "PIP_NO_INDEX",
        "PIP_REQUIREMENT",
    }
)
RESOLVER_SOURCE_ENV_VARS = frozenset(
    UV_INDEX_ENV_VARS | UV_REQUIREMENT_SOURCE_ENV_VARS | PIP_REQUIREMENT_SOURCE_ENV_VARS
)
DIAGNOSTIC_MAX_CHARS = 4000
FAILURE_REASON_MAX_CHARS = 600
_URL_RE = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)
FRESH_STATUS_ERROR_CODES = frozenset(
    {
        "config_missing",
        "schema_version",
        "connections_required",
        "active_env_required",
        "active_env",
        "temp_root_not_writable",
        "cache_dir_not_writable",
    }
)


class InstallError(RuntimeError):
    """Raised for user-actionable installer failures."""


@dataclass(frozen=True)
class InstallOptions:
    channel: str
    version: str | None
    yes: bool
    dry_run: bool
    base_url: str
    no_setup: bool


def main(argv: Iterable[str] | None = None) -> int:
    try:
        Installer(parse_args(argv)).run()
    except InstallError as exc:
        gutter = Installer._gutter(sys.stderr)
        print(f"{gutter} {_sanitize_diagnostic(str(exc))}", file=sys.stderr)
        return 1
    return 0


def parse_args(argv: Iterable[str] | None = None) -> InstallOptions:
    parser = argparse.ArgumentParser(description="Install Yoke.")
    parser.add_argument(
        "--channel", default=os.environ.get("YOKE_CHANNEL") or DEFAULT_CHANNEL
    )
    parser.add_argument("--version", default=os.environ.get("YOKE_VERSION") or None)
    parser.add_argument(
        "--yes", action="store_true", default=_env_truthy("YOKE_INSTALL_YES")
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Confirm the resolved version is published at the installer origin "
            "and print the install plan. Does not install packages or write "
            "configuration. A published release is not proof the install would "
            "succeed."
        ),
    )
    parser.add_argument(
        "--no-setup", action="store_true", default=_env_truthy("YOKE_NO_SETUP")
    )
    parser.add_argument(
        "--base-url",
        help=argparse.SUPPRESS,
        default=os.environ.get("YOKE_INSTALL_BASE_URL") or DEFAULT_BASE_URL,
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    return InstallOptions(
        channel=args.channel,
        version=args.version,
        yes=bool(args.yes),
        dry_run=bool(args.dry_run),
        base_url=args.base_url.rstrip("/"),
        no_setup=bool(args.no_setup),
    )
