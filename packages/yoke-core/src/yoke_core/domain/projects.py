"""Project-domain CRUD and capability management.

Manages projects, sites, environments, capability_templates,
project_capabilities, capability_secrets, and ephemeral_environments.

CLI usage::

    python3 -m yoke_core.domain.projects <subcmd> [args...]

Subcommands:

    init, create, get, list, update, has-capability,
    capability-get-settings, capability-set-settings, capability-merge-settings,
    capability-get-secret, capability-set-secret, capability-list-secrets,
    capability-list,
    environment-get-settings, environment-set-settings,
    environment-merge-settings,
    resolve-deploy-envs

Settings writers are lost-update protected: full-document set-settings is
compare-and-swap on the as-read text (``--base``; ``--new`` creates a
capability), merge-settings composes single keys; a stale base exits 1
with a ``settings_conflict`` teaching message.

Exit codes: 0 success, 1 error/not-found/conflict, 2 usage error.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from yoke_core.domain.db_helpers import (  # noqa: F401
    connect,
    iso8601_now,
    query_one,
    query_rows,
    query_scalar,
)
from yoke_core.domain.projects_restart import (  # noqa: F401
    cmd_init,
    cmd_resolve_deploy_envs,
)
from yoke_core.domain.projects_environments_settings import (
    ENVIRONMENT_SETTINGS_COMMANDS,
    register_environment_settings_parsers,
    run_environment_settings_command,
)
from yoke_core.domain.projects_capabilities_settings import (  # noqa: F401
    CAPABILITY_SETTINGS_COMMANDS,
    _canonicalize_capability_settings,
    cmd_capability_get_settings,
    cmd_capability_merge_settings,
    cmd_capability_set_settings,
    register_capability_settings_parsers,
    run_capability_settings_command,
)
from yoke_core.domain.projects_capability_secrets_command import (
    CAPABILITY_SECRET_COMMANDS,
    register_capability_secret_parsers,
    run_capability_secret_command,
)
from yoke_core.domain.settings_cas import SettingsConflictError
from yoke_core.domain.projects_render import (  # noqa: F401
    TestCommandResult,
    _split_command_chain,
    _resolve_under_cwd,
    _validate_test_command,
    validate_project_test_commands,
    format_validation_block,
    cmd_validate_test_commands,
)
from yoke_core.domain.projects_capabilities import (  # noqa: F401
    capability_secret_value_from_args,
    cmd_capability_get_secret,
    cmd_capability_list,
    cmd_capability_list_secrets,
    cmd_capability_mark_machine_secret_file,
    cmd_capability_set_secret,
    list_capability_settings_by_type,
)


# ---------------------------------------------------------------------------
# Valid fields on the projects table
# ---------------------------------------------------------------------------

PROJECT_FIELDS = (
    "id", "slug", "name", "emoji", "default_branch",
    "github_repo", "public_item_prefix", "github_sync_mode",
    "created_at",
)

# Full-row SELECT columns for ``get`` (all-fields mode)
_PROJECT_SELECT = ", ".join(PROJECT_FIELDS)

# Fields returned by ``list`` (stable pipe-delimited output)
_PROJECT_LIST_FIELDS = (
    "id", "slug", "name", "default_branch",
    "created_at",
)
_PROJECT_LIST_SELECT = ", ".join(_PROJECT_LIST_FIELDS)

# Secret-key heuristic patterns used by config-split migration
_SECRET_PATTERNS = ("token", "secret", "password", "api_key", "access_key", "private_key")


# Project-row CRUD needs the constants above during lazy parent resolution.
from yoke_core.domain.projects_crud import (  # noqa: F401, E402
    _pipe_row,
    _pipe_rows,
    cmd_create,
    cmd_get,
    cmd_has_capability,
    cmd_list,
    cmd_update,
)
from yoke_core.domain.projects_upsert import cmd_upsert  # noqa: F401, E402

# ---------------------------------------------------------------------------
# CLI argument parser
def _build_parser() -> "argparse.ArgumentParser":
    parser = argparse.ArgumentParser(
        prog="project-db",
        description="Project-domain CRUD for the Yoke DB",
    )
    sub = parser.add_subparsers(dest="command")

    # init
    sub.add_parser("init", help="Create tables + seed data (idempotent)")

    # create
    p = sub.add_parser("create", help="Insert a new project")
    p.add_argument("id")
    p.add_argument("name")

    # get
    p = sub.add_parser("get", help="Get project (pipe-delimited or single field)")
    p.add_argument("id")
    p.add_argument("field", nargs="?", default=None)

    # list
    sub.add_parser("list", help="List all projects (pipe-delimited)")

    # update
    p = sub.add_parser("update", help="Update a single field")
    p.add_argument("id")
    p.add_argument("field")
    p.add_argument("value", nargs="?", default="")

    # has-capability
    p = sub.add_parser("has-capability", help="Check if project has capability (exit 0/1)")
    p.add_argument("project")
    p.add_argument("type")
    p.add_argument(
        "--json", dest="json_mode", action="store_true",
        help=(
            "Route through the function dispatcher and emit the typed "
            "FunctionCallResponse envelope (avoids "
            "'2>&1; echo $?' shell choreography)."
        ),
    )

    # capability-list
    p = sub.add_parser("capability-list", help="List capability types for a project")
    p.add_argument("project")

    # capability-get-settings / capability-set-settings / capability-merge-settings
    register_capability_settings_parsers(sub)

    register_capability_secret_parsers(sub)

    # environment-get-settings / environment-set-settings
    register_environment_settings_parsers(sub)

    # resolve-deploy-envs
    p = sub.add_parser("resolve-deploy-envs", help="List valid deployment envs (DB only)")
    p.add_argument("project")

    # validate-test-commands
    p = sub.add_parser(
        "validate-test-commands",
        help="Validate configured project test commands (quick/full/e2e/smoke)",
    )
    p.add_argument("project", nargs="?", default=None)
    p.add_argument(
        "--all",
        action="store_true",
        dest="all_projects",
        help="Validate every project",
    )

    return parser


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help(sys.stderr)
        return 2

    try:
        if args.command == "init":
            cmd_init()
            return 0

        elif args.command == "create":
            print(cmd_create(args.id, args.name))
            return 0

        elif args.command == "get":
            result = cmd_get(args.id, field=args.field)
            if result is None:
                print(f"Error: project '{args.id}' not found", file=sys.stderr)
                return 1
            print(result)
            return 0

        elif args.command == "list":
            output = cmd_list()
            if output:
                print(output)
            return 0

        elif args.command == "update":
            print(cmd_update(args.id, args.field, args.value))
            return 0

        elif args.command == "has-capability":
            if getattr(args, "json_mode", False):
                # Route through the function dispatcher and emit the typed
                # envelope. Operators can read structured success/result
                # without ``2>&1; echo $?`` choreography.
                from yoke_core.domain.handlers.__init_register__ import (
                    register_all_handlers,
                )
                from yoke_contracts.api.function_call import TargetRef
                from yoke_core.api.service_client_structured_api_adapter import (
                    call_dispatcher,
                    emit_response,
                )

                register_all_handlers()
                response = call_dispatcher(
                    function_id="projects.capability.has",
                    target=TargetRef(kind="global"),
                    payload={"project": args.project, "cap_type": args.type},
                )
                return emit_response(response, json_mode=True)
            if cmd_has_capability(args.project, args.type):
                return 0
            else:
                return 1

        elif args.command == "capability-list":
            output = cmd_capability_list(args.project)
            if output:
                print(output)
            return 0

        elif args.command in CAPABILITY_SETTINGS_COMMANDS:
            return run_capability_settings_command(args)

        elif args.command in CAPABILITY_SECRET_COMMANDS:
            return run_capability_secret_command(args)

        elif args.command in ENVIRONMENT_SETTINGS_COMMANDS:
            return run_environment_settings_command(args)

        elif args.command == "resolve-deploy-envs":
            result = cmd_resolve_deploy_envs(args.project)
            if result is None:
                return 1
            print(result)
            return 0

        elif args.command == "validate-test-commands":
            try:
                output, exit_code = cmd_validate_test_commands(
                    project_id=args.project,
                    all_projects=args.all_projects,
                )
            except LookupError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                return 1
            if output:
                print(output)
            return exit_code

        else:
            parser.print_help(sys.stderr)
            return 2

    except SettingsConflictError as exc:
        # Typed CAS refusal carrying the settings_conflict re-get teaching.
        print(str(exc), file=sys.stderr)
        return 1
    except (ValueError, LookupError) as exc:
        print(str(exc), file=sys.stderr)
        if isinstance(exc, ValueError):
            return 2
        return 1
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
