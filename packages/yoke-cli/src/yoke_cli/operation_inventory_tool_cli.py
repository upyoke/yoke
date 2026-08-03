"""First-class ``yoke`` commands that stay local and carry no function id."""

from __future__ import annotations

from typing import Tuple

from yoke_cli.operation_inventory_model import _Row, _t


# These adapters are real CLI surfaces, but they execute local subprocesses
# rather than dispatching a control-plane operation. Keeping that distinction
# explicit prevents a fabricated function id from making the registry look
# wrapped when it is not.
TOOL_CLI_ROWS: Tuple[_Row, ...] = (
    _t("yoke watch pytest", "tools.watch"),
    _t("yoke watch doctor", "tools.watch"),
    _t("yoke watch merge", "tools.watch"),
)


__all__ = ["TOOL_CLI_ROWS"]
