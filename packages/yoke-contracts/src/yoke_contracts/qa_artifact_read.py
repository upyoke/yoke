"""The one recipe that turns a recorded QA artifact into readable bytes.

A capture writes its screenshots into per-run scratch under the machine
temp root, and the session-cwd guard refuses that tree from a session
holding a lane claim — so the path a capture reports is not a path its
reviewer can open, and a reviewer handed only paths has to discover the
portable route before it can look at anything. The portable route is the
recorded artifact id through ``yoke qa artifact read``, which lands the
bytes under :func:`yoke_contracts.free_paths.free_temp_root`, a directory
every guard already admits.

Every surface that hands an agent a captured artifact — capture
completion, the agent review bundle, the owner decision context — names
that command from here, so the recipe has one owner and cannot drift
between the surface that offers it and the command that answers it.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from yoke_contracts.free_paths import free_temp_root


#: Directory name under the free temp root where read bytes land.
ARTIFACT_READ_DIR_NAME = "yoke-qa-artifacts"

#: Used when the recorded content type names no known extension.
DEFAULT_ARTIFACT_SUFFIX = ".bin"


def artifact_read_command(requirement_id: int, artifact_id: int) -> str:
    """Return the ready-to-run command that lands one artifact's bytes.

    ``--output`` is deliberately absent: the destination has to be
    resolved on the machine that runs the command, so a relayed control
    plane composing this string cannot bake its own temp root into a
    recipe the client would then be refused for.
    """
    return (
        "yoke qa artifact read "
        f"--requirement-id {int(requirement_id)} "
        f"--artifact-id {int(artifact_id)}"
    )


def artifact_read_destination(
    artifact_id: int,
    *,
    content_type: str | None = None,
    create_parent: bool = True,
) -> Path:
    """Return where ``yoke qa artifact read`` lands *artifact_id*'s bytes.

    The name is a function of the artifact id alone, so re-reading the
    same artifact converges on one file instead of littering the root.
    """
    suffix = _suffix_for(content_type)
    path = free_temp_root() / ARTIFACT_READ_DIR_NAME / (
        f"qa-artifact-{int(artifact_id)}{suffix}"
    )
    if create_parent:
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _suffix_for(content_type: str | None) -> str:
    """Map a recorded MIME type to a file suffix a viewer will honor."""
    if not content_type:
        return DEFAULT_ARTIFACT_SUFFIX
    base = str(content_type).split(";", 1)[0].strip()
    if not base:
        return DEFAULT_ARTIFACT_SUFFIX
    if base == "image/jpeg":
        # guess_extension answers ".jpe" here, which no viewer expects.
        return ".jpg"
    return mimetypes.guess_extension(base) or DEFAULT_ARTIFACT_SUFFIX


__all__ = [
    "ARTIFACT_READ_DIR_NAME",
    "DEFAULT_ARTIFACT_SUFFIX",
    "artifact_read_command",
    "artifact_read_destination",
]
