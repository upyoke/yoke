"""Render the workbench's harness-name module from the harness registry.

The browser cannot import Python, so the readable harness names the
workbench teaches with ship as a generated static module. The registry in
:mod:`yoke_contracts.executor_labels` stays the one authority; ``check``
refuses a module that drifted from it.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Optional, Sequence

from yoke_contracts.executor_labels import (
    CANONICAL_HARNESS_IDS,
    harness_display_name,
)
from yoke_core.domain.workspace_authority import (
    assert_target_under_session_work_authority,
)


MODULE_REL = Path("packages/yoke-core/src/yoke_core/ui/static/harness_names.js")
SYNC_COMMAND = "python3 -m yoke_core.ui.harness_names_module sync"


def render_module() -> str:
    names = [harness_display_name(harness_id) for harness_id in CANONICAL_HARNESS_IDS]
    return (
        "// Generated from yoke_contracts.executor_labels; do not edit.\n"
        f"// Regenerate: {SYNC_COMMAND}\n"
        "// Every supported harness, in registry order, as a person reads it.\n"
        f"export const HARNESS_NAMES = {json.dumps(names)};\n"
    )


def has_drift(*, target_root: Path) -> bool:
    path = target_root / MODULE_REL
    return not path.is_file() or path.read_text(encoding="utf-8") != render_module()


def sync(*, target_root: Path) -> bool:
    """Write the module when it differs; return whether it was written."""
    if not has_drift(target_root=target_root):
        return False
    path = target_root / MODULE_REL
    assert_target_under_session_work_authority(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(render_module(), encoding="utf-8")
    os.replace(temporary, path)
    return True


def run_cli(argv: Optional[Sequence[str]] = None) -> int:
    from yoke_core.domain.agents_render_workspace import resolve_target_root_for_cli

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("sync", "check"):
        subparsers.add_parser(command).add_argument("--target-root", default=None)
    args = parser.parse_args(argv)
    target_root = resolve_target_root_for_cli(args.target_root)
    if args.command == "sync":
        written = sync(target_root=target_root)
        print(f"{MODULE_REL.name}: " + ("written" if written else "in sync"))
        return 0
    if has_drift(target_root=target_root):
        print(f"{MODULE_REL.name} drifted from the harness registry")
        print(f"Repair: {SYNC_COMMAND}")
        return 1
    print(f"{MODULE_REL.name}: in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
