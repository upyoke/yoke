"""Name guards the hook deadline skipped so a silent hole is visible."""

from __future__ import annotations

import sys
from typing import Optional

from yoke_core.hooks.remote_policy import RunControls


def record_skipped_guards(
    skipped: list[str],
    controls: Optional[RunControls],
) -> None:
    marker = f"deadline_skipped:{len(skipped)}:{','.join(skipped)}"
    if controls is not None:
        controls.degraded.append(marker)
    print(
        f"hook runner: deadline exhausted; skipped {len(skipped)} guards: "
        f"{', '.join(skipped)}",
        file=sys.stderr,
    )
