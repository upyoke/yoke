"""``yoke universe import``: adopt a restored universe on this machine.

Sibling of :mod:`yoke_cli.commands.local_universe`. Import is the one
local-universe command that changes which actor this machine operates
the universe as, so it also reports whether that binding was recorded —
a universe adopted without one cannot register a session until the
operator runs the command the warning names.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List

from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_cli.commands.local_universe_usage import IMPORT_USAGE
from yoke_cli.config import local_universe_setup as setup


def universe_import(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke universe import",
        description=(
            "Replace the active machine-local universe from one portable "
            "archive. The archive carries its own checksum receipt; deployed "
            "code supplies the schema, imported remote credentials are "
            "revoked, and the machine owner receives local admin authority."
        ),
    )
    parser.add_argument("archive")
    parser.add_argument(
        "--yes",
        dest="assume_yes",
        action="store_true",
        help="Consent to replacing the active local universe without a prompt.",
    )
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parse_or_usage_error(parser, args, IMPORT_USAGE)
    if parsed is None:
        return 2
    if not parsed.assume_yes:
        if not sys.stdin.isatty():
            print(
                "error: importing replaces the active local universe; pass "
                "--yes to consent when running non-interactively",
                file=sys.stderr,
            )
            return 1
        try:
            response = input(
                "This import replaces the active local universe. "
                "Type 'replace' to continue: "
            )
        except EOFError:
            response = ""
        if response.strip().lower() != "replace":
            print("error: import cancelled", file=sys.stderr)
            return 1
    try:
        report = setup.universe_import(archive=parsed.archive)
    except setup.LocalUniverseSetupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if parsed.json_mode:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"universe imported: {report.get('org')}")
        print(f"local owner: {report.get('actor_label')}")
        binding_error = str(report.get("operating_actor_binding_error") or "")
        if binding_error:
            print(
                "warning: this machine's operating-actor binding was not "
                f"recorded ({binding_error}); run `yoke config bind-actor "
                f"--actor-id {report.get('actor_id')}` before registering a "
                "session"
            )
        archive = report.get("archive") or {}
        print(f"archive: {archive.get('path')}")
    return 0



__all__ = ["universe_import"]
