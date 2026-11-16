"""The line limit for Yoke's own shipped documentation.

Yoke's public docs are authored in the Yoke source repository, so they obey
that repository's ``file_line_limit``, never the limit of the project that
installs them: a project that sets a smaller limit must still build its
install bundle. A source checkout resolves the setting from the checkout
this module runs from; an installed wheel has no source checkout and uses
the default, which is the limit the release was built under unless the
Yoke repository sets its own.
"""

from __future__ import annotations

from pathlib import Path

from yoke_contracts.project_contract.file_line_policy import (
    DEFAULT_LIMIT,
    project_limit,
)

# packages/yoke-core/src/yoke_core/domain/<this file> -> the source checkout.
_SOURCE_CHECKOUT = Path(__file__).resolve().parents[5]
_SOURCE_MARKER = "packages/yoke-core/src/yoke_core"


def documentation_line_limit() -> int:
    """Resolve the Yoke source repository's authored-file line limit."""
    if (_SOURCE_CHECKOUT / _SOURCE_MARKER).is_dir():
        return project_limit(_SOURCE_CHECKOUT)
    return DEFAULT_LIMIT


__all__ = ["documentation_line_limit"]
