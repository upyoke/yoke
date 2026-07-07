"""Shared helpers for cutoff regression tests.

Underscore prefix keeps pytest from collecting this as a test module.
Used by ``test_doctor_hc_meta_cutoffs.py``,
``test_doctor_hc_meta_cutoffs_extra.py``, and
``test_doctor_hc_db_full_runs_cutoffs.py`` to:

  * write a one-key machine config under ``tmp_path``, and
  * patch the shared repo-root/config resolvers so the HC reads that file.
"""

from __future__ import annotations

import json
import os
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch


def _write_cutoff(tmp_path: Path, key: str, value) -> None:
    """Write ``.yoke/config.json`` under ``tmp_path`` with one cutoff key set.

    Idempotent on ``.yoke/``; safe to call multiple times per test if a
    later seed step needs to overwrite the config.
    """
    config_path = tmp_path / ".yoke" / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"settings": {}}
    if config_path.is_file():
        try:
            loaded = json.loads(config_path.read_text())
        except ValueError:
            loaded = {}
        if isinstance(loaded, dict):
            payload.update(loaded)
    settings = payload.get("settings")
    if not isinstance(settings, dict):
        settings = {}
    settings[key] = value
    payload["settings"] = settings
    config_path.write_text(json.dumps(payload, sort_keys=True) + "\n")


@contextmanager
def _patch_repo_root(tmp_path: Path):
    """Patch the shared repo-root and machine config resolver.

    Returns a context-manager patch object; use as ``with _patch_repo_root(p): ...``.
    """
    config_path = tmp_path / ".yoke" / "config.json"
    if not config_path.is_file():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text('{"settings": {}}\n')
    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "yoke_core.engines.doctor_report._resolve_repo_root",
                return_value=str(tmp_path),
            )
        )
        stack.enter_context(
            patch.dict(os.environ, {"YOKE_MACHINE_CONFIG_FILE": str(config_path)})
        )
        yield
