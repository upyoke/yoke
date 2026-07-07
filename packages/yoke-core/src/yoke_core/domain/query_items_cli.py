"""Compatibility CLI behind ``query-items.sh``.

Preserves the historical shell-facing command shape while delegating
all behavior to the Python service client.
"""
from __future__ import annotations

import sys
from typing import Iterable, Optional

from yoke_core.api import service_client
from yoke_core.api.service_client_items_parsing import _QI_ALL_FIELDS

_USAGE = """\
Usage:
  db_router items list [--status S] [--priority S] [--type S] [--frozen 0|1] [--project P] [--fields "f1,f2,..."] [--limit N]
  db_router items count [--status S] [--priority S] [--type S] [--frozen 0|1] [--project P]
  db_router items get YOK-N <field> [<field2> ...] [--section "## Heading"] [--json]
  db_router items row YOK-N
  db_router items progress YOK-N

Worked example — canonical agent shape:
  yoke items get YOK-N status type title
  yoke items get YOK-N spec

Operator-debug fallback inside a Yoke checkout (also offers --section
body filtering the `yoke items get` adapter does not expose yet):
  python3 -m yoke_core.cli.db_router items get YOK-N status type title
  python3 -m yoke_core.cli.db_router items get YOK-N body          # virtual rendered field
  python3 -m yoke_core.cli.db_router items get YOK-N spec --section "## Acceptance Criteria"

Field matrix for `get` (canonical YOKE backlog item columns):
  scalar:  id, title, status, type, priority, project, deployment_flow,
           frozen, blocked, blocked_reason, worktree, github_issue, deployed_to
  structured: spec, design_spec, technical_plan, worktree_plan,
              shepherd_log, shepherd_caveats, test_results, deploy_log
  virtual: body (rendered on demand from structured fields + sections;
           NEVER stored — raw body writes are unsupported)

Notes:
  - `YOK-N` accepts a `YOK-`-prefixed or bare-integer item id.
  - `--section "## H"` restricts output to one named section of a structured field.
  - `--json` emits one JSON object per row for machine consumers.

Exit codes: 0 = results, 1 = no results, 2 = usage error
"""


def _usage(err: bool = False) -> int:
    stream = sys.stderr if err else sys.stdout
    print(_USAGE, file=stream, end="")
    return 0 if not err else 2


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    subcmd = args[0] if args else ""
    rest = args[1:]

    if subcmd in ("-h", "--help", "help"):
        return _usage(err=False)
    # ``<subcmd> --help`` short-circuits to the canonical usage banner
    # before the per-subcommand argument validators fire.
    if rest and rest[0] in ("-h", "--help"):
        return _usage(err=False)
    if subcmd == "":
        print("Error: subcommand required", file=sys.stderr)
        return _usage(err=True)
    if subcmd == "list":
        return service_client.cmd_item_list(rest)
    if subcmd == "count":
        return service_client.cmd_item_count(rest)
    if subcmd == "get":
        if len(rest) < 2:
            print("Error: get requires YOK-N and field", file=sys.stderr)
            return _usage(err=True)
        item_arg = rest[0]
        fields = [arg for arg in rest[1:] if arg != "--json"]
        if not fields:
            print("Error: get requires YOK-N and field", file=sys.stderr)
            return _usage(err=True)
        for field in fields:
            if field not in _QI_ALL_FIELDS:
                print(
                    f"Error: unknown field '{field}'. Valid: "
                    f"{','.join(sorted(_QI_ALL_FIELDS))}",
                    file=sys.stderr,
                )
                return 2
        for field in fields:
            rc = service_client.cmd_item_get([item_arg, field])
            if rc != 0:
                return rc
        return 0
    if subcmd == "row":
        if len(rest) < 1:
            print("Error: row requires YOK-N", file=sys.stderr)
            return _usage(err=True)
        return service_client.cmd_item_row(rest[:1])
    if subcmd == "progress":
        if len(rest) < 1:
            print("Error: progress requires YOK-N", file=sys.stderr)
            return _usage(err=True)
        return service_client.cmd_item_progress(rest[:1])
    if subcmd == "render":
        if len(rest) < 1:
            print("Error: render requires YOK-N", file=sys.stderr)
            return _usage(err=True)
        return service_client.cmd_item_render(rest[:1])

    print(f"Error: unknown subcommand '{subcmd}'", file=sys.stderr)
    return _usage(err=True)


if __name__ == "__main__":
    sys.exit(main())
