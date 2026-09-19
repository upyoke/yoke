"""Argument tree for the browser daemon client.

Kept beside the client rather than inside it: the client is a transport,
and an argparse tree is a hundred lines of vocabulary that says nothing
about how a daemon call is made. Handlers live in ``browser_client_cli``.
"""

from __future__ import annotations

import argparse




def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="browser_client",
        description="Browser daemon client and lifecycle management",
    )
    sub = parser.add_subparsers(dest="cmd")

    # daemon
    d = sub.add_parser("daemon")
    dsub = d.add_subparsers(dest="daemon_cmd")
    dsub.add_parser("status")
    dsub.add_parser("health")
    ds = dsub.add_parser("start")
    ds.add_argument("--port", type=int)
    ds.add_argument("--headed", action="store_true")
    ds.add_argument("--project", default=None)
    ds.add_argument("--idle-timeout", type=int, dest="idle_timeout")
    dsub.add_parser("stop")

    # snapshot
    s = sub.add_parser("snapshot")
    ssub = s.add_subparsers(dest="snap_cmd")
    sa = ssub.add_parser("accessibility")
    sa.add_argument("url")
    ss = ssub.add_parser("screenshot")
    ss.add_argument("url")
    ss.add_argument("--annotate", action="store_true")
    ss.add_argument("--output")
    ss.add_argument("--viewport")
    sd = ssub.add_parser("diff")
    sd.add_argument("url")
    sd.add_argument("--baseline", required=True)
    sd.add_argument("--viewport", required=True)
    sd.add_argument("--output-dir", dest="output_dir")
    sd.add_argument("--threshold", type=float)

    # exec
    e = sub.add_parser("exec")
    esub = e.add_subparsers(dest="exec_cmd")
    es = esub.add_parser("step")
    es.add_argument("step_json")
    es.add_argument("--base-url", required=True, dest="base_url")
    es.add_argument("--output-dir", dest="output_dir")
    es.add_argument(
        "--page-id", dest="page_id",
        help="Page to act on (default: the shared diagnostic page).",
    )

    return parser
