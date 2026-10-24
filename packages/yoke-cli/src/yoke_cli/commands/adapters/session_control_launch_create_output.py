"""Write a launch create result, naming a level the server did not record."""

from __future__ import annotations

import json
from typing import Any

from yoke_cli.commands.adapters.session_control_common import write_launch_result


def create_result_writer(payload: dict[str, Any]) -> Any:
    """Name the gap when a server predating item levels recorded none.

    A server that records the item level always echoes ``item_level`` for an
    item-bound create at a named level; its absence means that server placed
    this one launch only.
    """
    item, level = payload.get("item"), payload.get("level")

    def write(response: Any, stdout: Any, stderr: Any) -> None:
        write_launch_result(response, stdout, stderr)
        result = response.result or {}
        if (
            item
            and level
            and not result.get("deduplicated")
            and not result.get("item_level")
        ):
            pin = json.dumps({"min": level, "max": level, "reason": "<why>"})
            print(
                "warning: item_level_unrecorded: this server predates launch-time "
                f"item levels, so --level {level} placed this launch only. Record "
                f"it for every stage: yoke workflows item-posture amend {item} "
                f"--key level --value '{pin}' --reason R",
                file=stderr,
            )

    return write


__all__ = ["create_result_writer"]
