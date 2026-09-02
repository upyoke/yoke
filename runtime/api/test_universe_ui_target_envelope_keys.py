"""The shipped web client never builds a target on a retired key.

The envelope validator refuses a retired target key loudly, so a client
still sending one fails at the server with an HTTP 422 the operator meets
as a dead link. The rename that retires a key has to reach the shipped
JavaScript in the same change; this check is what says so.
"""

from __future__ import annotations

import re
from importlib.resources import files

from yoke_contracts.api.function_call import RETIRED_TARGET_KEYS

from yoke_core.ui import server as ui_server


def test_no_shipped_module_sends_a_retired_target_key() -> None:
    static_root = files("yoke_core.ui").joinpath("static")
    # Key position (``item_ref:``) is the envelope a client builds; the
    # value position (``row.item_ref``) reads a server response field and
    # is untouched by a target-key rename.
    patterns = {
        retired: re.compile(rf"\b{re.escape(retired)}\s*:")
        for retired in RETIRED_TARGET_KEYS
    }
    offenders = []
    for module_name in sorted(ui_server.ASSET_CONTENT_TYPES):
        if not module_name.endswith(".js"):
            continue
        source = static_root.joinpath(module_name).read_text(encoding="utf-8")
        for number, line in enumerate(source.splitlines(), start=1):
            for retired, pattern in patterns.items():
                if pattern.search(line):
                    offenders.append(
                        f"{module_name}:{number} sends retired target key "
                        f"{retired!r} — use {RETIRED_TARGET_KEYS[retired]!r}"
                    )
    assert not offenders, "\n".join(offenders)
