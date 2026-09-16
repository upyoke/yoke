"""The one recipe that turns a recorded QA artifact into readable bytes.

A capture writes its screenshots into per-run scratch under the machine
temp root, and the session-cwd guard refuses that tree from a session
holding a lane claim — so the path a capture reports is not a path its
reviewer can open, and a reviewer handed only paths has to discover the
portable route before it can look at anything. The portable route is the
recorded artifact id through ``yoke qa artifact read``, which lands the
bytes in a fresh private directory under the machine temp root, which
every guard already admits, and reports where they landed.

Every surface that hands an agent a captured artifact — capture
completion, the agent review bundle, the owner decision context — names
that command from here, so the recipe has one owner and cannot drift
between the surface that offers it and the command that answers it.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from yoke_contracts.free_paths import private_free_path


#: Names the private per-read directory the bytes land inside.
ARTIFACT_READ_DIR_PREFIX = "yoke-qa-artifact."

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
) -> Path:
    """Return a fresh private path for *artifact_id*'s bytes.

    A new directory per read rather than one path per artifact id,
    because an id is unique only within the control plane that issued
    it: the same number names different evidence on another connection,
    and one shared temp root would let the second read overwrite the
    first. The caller reports the path this returns, so the reader is
    told where the bytes actually landed rather than deducing it.
    """
    return private_free_path(
        f"qa-artifact-{int(artifact_id)}{_suffix_for(content_type)}",
        prefix=ARTIFACT_READ_DIR_PREFIX,
    )


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
    "ARTIFACT_READ_DIR_PREFIX",
    "DEFAULT_ARTIFACT_SUFFIX",
    "artifact_read_command",
    "artifact_read_destination",
]
