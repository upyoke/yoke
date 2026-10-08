"""Package the locked npm chart dependency as offline wheel assets.

Run npm ci in this module's directory, then this module with --target-root.
The product serves these generated assets locally; browsers never use a CDN.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from yoke_core.domain.workspace_authority import (
    assert_target_under_session_work_authority,
)

UI_PATH = Path("packages/yoke-core/src/yoke_core/ui")


def build(*, target_root: Path) -> None:
    root = target_root / UI_PATH
    source = root / "node_modules/uplot"
    artifacts = {
        "uplot.js": (source / "dist/uPlot.iife.min.js").read_text()
        + "\nexport default uPlot;\n",
        "uplot.css": (source / "dist/uPlot.min.css").read_text(),
        "uplot-license.txt": (source / "LICENSE").read_text(),
    }
    for name, content in artifacts.items():
        path = root / "static" / name
        assert_target_under_session_work_authority(path)
        path.write_text(content)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-root", type=Path, required=True)
    build(target_root=parser.parse_args().target_root)
