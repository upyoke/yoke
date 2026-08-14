"""Keep the owning session live for one deployment-pipeline process."""

from __future__ import annotations

import sys
from typing import List, Optional

from yoke_core.domain import deploy_pipeline
from yoke_core.domain.session_liveness_pump import SessionLivenessPump


def main(argv: Optional[List[str]] = None) -> int:
    """Execute the deployment pipeline inside a bounded liveness scope."""
    with SessionLivenessPump().running():
        return deploy_pipeline.main(argv)


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main(list(sys.argv[1:])))


__all__ = ["main"]
