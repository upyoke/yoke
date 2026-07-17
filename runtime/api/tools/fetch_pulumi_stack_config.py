"""Fetch a project's pulumi-stack-config snapshot over the active connection.

Source-dev/admin helper mirroring the deployment preflight's authenticated
GET of ``/v1/projects/<project>/pulumi-stack-config``. Reuses the machine's
active https connection and bearer token; the token is never printed. The
body is written to ``--output`` for use as a ``runner-fleet exec``
settings file.

Usage:
    python3 -m runtime.api.tools.fetch_pulumi_stack_config \
        --project platform --output /tmp/pulumi-stack-config.json
"""

from __future__ import annotations

import argparse
import sys
import urllib.request

from yoke_cli.api_urls import join_api_url
from yoke_cli.transport.https import resolve_https_connection


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fetch_pulumi_stack_config",
        description=__doc__.splitlines()[0],
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--output", required=True)
    parsed = parser.parse_args(argv)

    connection = resolve_https_connection()
    if connection is None:
        print(
            "error: active connection is not https transport",
            file=sys.stderr,
        )
        return 1
    url = join_api_url(
        connection.api_url,
        f"/v1/projects/{parsed.project}/pulumi-stack-config",
    )
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {connection.token}"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read()
    with open(parsed.output, "wb") as handle:
        handle.write(body)
    print(f"wrote {len(body)} bytes to {parsed.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
