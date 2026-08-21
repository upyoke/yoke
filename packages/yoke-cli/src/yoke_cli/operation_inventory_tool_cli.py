"""First-class ``yoke`` commands that stay local and carry no function id."""

from __future__ import annotations

from typing import Tuple

from yoke_cli.operation_inventory_model import _Row, _t


# These adapters are real CLI surfaces, but they execute local subprocesses
# rather than dispatching a control-plane operation. Keeping that distinction
# explicit prevents a fabricated function id from making the registry look
# wrapped when it is not.
TOOL_CLI_ROWS: Tuple[_Row, ...] = (
    _t("yoke advance implementation-entry", "tools.advance_implementation_entry"),
    _t("yoke dev run", "tools.source_dev_run"),
    _t("yoke watch pytest", "tools.watch"),
    _t("yoke watch doctor", "tools.watch"),
    _t("yoke watch merge", "tools.watch"),
    _t("yoke watch qa-case", "tools.watch"),
    _t("yoke watch qa-plan", "tools.watch"),
    _t("yoke release-pin verify", "tools.release_pin"),
)


__all__ = ["TOOL_CLI_ROWS"]
