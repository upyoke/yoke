"""Explicit source resume for portable universe moves."""

import argparse
import json
import sys
import urllib.request

from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_cli.config import local_universe_setup as setup, onboard_destinations
from yoke_cli.api_urls import join_api_url
from yoke_cli.transport.https import TransportError, resolve_https_connection
from yoke_cli.transport.https_urlopen import open_no_redirect
from yoke_cli.commands.universe_upload import UPLOAD_USAGE, universe_upload

RESUME_USAGE = "yoke universe resume [--json]"


def universe_resume(args):
    parser = argparse.ArgumentParser(
        prog="yoke universe resume",
        description="Allow source writers after a move or failed export.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_mode",
        help="Print the resume receipt as JSON.",
    )
    parsed = parse_or_usage_error(parser, args, RESUME_USAGE)
    if parsed is None:
        return 2
    try:
        connection = resolve_https_connection()
        if connection is None:
            report = setup.universe_resume()
        elif onboard_destinations.is_hosted_url(connection.api_url):
            print(
                "error: universe_resume_dashboard_required: use Resume source in the dashboard's Universe portability controls",
                file=sys.stderr,
            )
            return 1
        else:
            request = urllib.request.Request(
                join_api_url(connection.api_url, "/v1/universe/resume"),
                method="POST",
                data=b"",
                headers={"Authorization": f"Bearer {connection.token}"},
            )
            with open_no_redirect(request, timeout=30) as response:
                report = json.loads(response.read(65537))
            if report.get("resumed") is not True:
                raise RuntimeError(
                    "universe_resume_unconfirmed: check source health and retry `yoke universe resume`"
                )
    except setup.LocalUniverseSetupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (RuntimeError, TransportError, OSError, ValueError):
        print(
            "error: universe_resume_failed: check source connection, org admin permission and pause-marker permissions, then retry `yoke universe resume`",
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(report)
        if parsed.json_mode
        else "Source resumed; writers may connect again."
    )
    return 0


TOOL_SHAPED_SUBCOMMANDS = {
    ("universe", "resume"): universe_resume,
    ("universe", "upload"): universe_upload,
}
TOOL_SHAPED_USAGE = {
    "yoke universe resume": RESUME_USAGE,
    "yoke universe upload": UPLOAD_USAGE,
}
