"""The public CLI excludes operations for internal hosted infrastructure."""

from yoke_cli.commands import installer_local, tool_shaped
from yoke_cli.operation_inventory_permanent import PERMANENT_ROWS


def test_internal_host_lifecycle_is_absent_from_the_public_cli():
    assert all(tokens[0] != "vps" for tokens in installer_local.TOOL_SHAPED_SUBCOMMANDS)
    assert all(tokens[0] != "vps" for tokens in tool_shaped.TOOL_SHAPED_SUBCOMMANDS)
    assert all(row.family != "vps" for row in PERMANENT_ROWS)
