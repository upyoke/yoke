"""Machine-owned universe archive filenames and output destinations."""

from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from yoke_contracts.timestamps import utc_now, parse_instant
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_core.domain.universe_archive import ARTIFACT_SUFFIX

_FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


class UniverseExportError(RuntimeError):
    """The universe could not be exported safely."""


def destination_unavailable(error: OSError) -> UniverseExportError:
    return UniverseExportError(
        compose_refusal(
            f"universe_export_destination_unavailable: {error}",
            recovery="repair the destination folder or pass --out with a writable archive path",
        )
    )


def default_artifact_name(
    org_slug: str,
    now: Optional[datetime] = None,
) -> str:
    """``<org-slug>-universe-<utc-timestamp>.tar``."""
    now = parse_instant(utc_now() if now is None else now)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    cleaned = _FILENAME_SAFE_RE.sub("-", org_slug).strip("-.")
    return f"{cleaned or 'universe'}-universe-{stamp}{ARTIFACT_SUFFIX}"


def resolve_export_destination(
    out: Optional[Union[str, Path]],
    org_slug: str,
) -> Path:
    """Route ``out`` to the artifact path.

    The trailing-separator check reads the raw text because ``Path``
    normalizes the separator away; without it a not-yet-created
    ``--out ~/backups/`` would silently become a file named ``backups``.
    """
    try:
        destination = _resolve_destination(out, org_slug)
        with tempfile.TemporaryFile(dir=destination.parent):
            pass
        return destination
    except OSError as exc:
        raise destination_unavailable(exc) from exc


def _resolve_destination(out: Optional[Union[str, Path]], org_slug: str) -> Path:
    if out is None:
        from yoke_core.domain.machine_config import yoke_home

        from yoke_contracts.machine_config.schema import DEFAULT_EXPORT_DIR_NAME

        out = yoke_home() / DEFAULT_EXPORT_DIR_NAME
        Path(out).mkdir(parents=True, exist_ok=True)
    raw = os.fspath(out)
    target = Path(raw).expanduser()
    if raw.endswith(("/", os.sep)) or target.is_dir():
        target.mkdir(parents=True, exist_ok=True)
        return target / default_artifact_name(org_slug)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target
