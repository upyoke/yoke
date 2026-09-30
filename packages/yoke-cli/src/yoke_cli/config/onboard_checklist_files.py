"""Write private onboarding records and project checklist views."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from yoke_contracts.machine_config.directories import create_private_directory


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    create_private_directory(path.parent)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    tmp_path.chmod(0o600)
    os.replace(tmp_path, path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
