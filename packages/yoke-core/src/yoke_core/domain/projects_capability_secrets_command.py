"""CLI parser/runner helpers for project capability secrets."""

from __future__ import annotations

from yoke_core.domain.projects_capabilities import (
    capability_secret_value_from_args,
    cmd_capability_get_secret,
    cmd_capability_list_secrets,
    cmd_capability_set_secret,
)

CAPABILITY_SECRET_COMMANDS = (
    "capability-get-secret",
    "capability-set-secret",
    "capability-list-secrets",
)


def register_capability_secret_parsers(sub) -> None:
    """Register capability secret CLI subcommands."""
    p = sub.add_parser("capability-get-secret", help="Get a secret value")
    p.add_argument("project")
    p.add_argument("type")
    p.add_argument("key")

    p = sub.add_parser("capability-set-secret", help="Set a secret value")
    p.add_argument("project")
    p.add_argument("type")
    p.add_argument("key")
    p.add_argument("value", nargs="?")
    p.add_argument("--value-file", dest="value_file", default=None)
    p.add_argument("--value-stdin", dest="value_stdin", action="store_true")

    p = sub.add_parser("capability-list-secrets", help="List secret keys")
    p.add_argument("project")
    p.add_argument("type")


def run_capability_secret_command(args) -> int:
    """Run a capability secret CLI command."""
    if args.command == "capability-get-secret":
        result = cmd_capability_get_secret(args.project, args.type, args.key)
        if result is None:
            return 1
        print(result)
        return 0

    if args.command == "capability-set-secret":
        print(cmd_capability_set_secret(
            args.project, args.type, args.key,
            value=capability_secret_value_from_args(args),
        ))
        return 0

    if args.command == "capability-list-secrets":
        output = cmd_capability_list_secrets(args.project, args.type)
        if output:
            print(output)
        return 0

    raise ValueError(f"unsupported capability secret command: {args.command}")
