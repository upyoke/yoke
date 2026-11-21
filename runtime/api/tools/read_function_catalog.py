"""Render the engine-free CLI read catalog from registered side effects."""

from __future__ import annotations

import argparse
from pathlib import Path
import textwrap


def registered_read_ids() -> frozenset[str]:
    from yoke_core.domain.function_connection_loss import side_effect_free
    from yoke_core.domain.handlers.__init_register__ import register_all_handlers
    from yoke_core.domain.yoke_function_registry import list_entries

    register_all_handlers()
    return frozenset(
        entry.function_id
        for entry in list_entries()
        if side_effect_free(entry)
    )


def registered_read_routes() -> frozenset[tuple[str, ...]]:
    """CLI routes, aliases included, whose function is a registered read."""
    from yoke_cli.commands.registry import (
        SUBCOMMAND_ALIAS_REGISTRY,
        SUBCOMMAND_REGISTRY,
    )

    reads = registered_read_ids()
    routes = {**SUBCOMMAND_REGISTRY, **SUBCOMMAND_ALIAS_REGISTRY}
    return frozenset(route for route, (fid, _) in routes.items() if fid in reads)


def render_source() -> str:
    names = textwrap.wrap(" ".join(sorted(registered_read_ids())), width=72)
    routes: list[str] = []
    for route in sorted(" ".join(route) for route in registered_read_routes()):
        if routes and len(routes[-1]) + len(route) < 72:
            routes[-1] += route + "|"
        else:
            routes.append(route + "|")
    return (
        '"""Generated read identities; regenerate with runtime.api.tools.read_function_catalog."""\n\n'
        "READ_FUNCTION_IDS = frozenset(\n    (\n"
        + "".join(f'        "{line} "\n' for line in names)
        + "    ).split()\n)\n\n"
        "# ``yoke`` CLI routes, aliases included, whose function is a read.\n"
        "READ_COMMAND_ROUTES = frozenset(\n    tuple(route.split())\n    for route in (\n"
        + "".join(f'        "{line}"\n' for line in routes)
        + '    ).split("|")\n    if route\n)\n'
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-root", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    target = args.target_root.resolve() / (
        "packages/yoke-contracts/src/yoke_contracts/registered_reads.py"
    )
    source = render_source()
    if args.check:
        if not target.is_file() or target.read_text() != source:
            parser.exit(
                1, "read_catalog_stale: regenerate with this command without --check\n"
            )
    else:
        from yoke_core.domain.workspace_authority import (
            assert_target_under_session_work_authority,
        )

        assert_target_under_session_work_authority(target)
        target.write_text(source)
    print(
        f"read catalog: {len(registered_read_ids())} registered reads,"
        f" {len(registered_read_routes())} read routes"
    )


if __name__ == "__main__":
    main()
