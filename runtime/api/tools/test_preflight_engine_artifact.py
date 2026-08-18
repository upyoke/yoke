"""Fleet preflight binds engine imports to the selected release wheel."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_selected_wheel_identity_is_digest_backed_and_source_cannot_win(
    tmp_path: Path,
) -> None:
    wheel = _engine_wheel(tmp_path, include_schema=True)

    result = _activate_in_clean_process(wheel)

    assert result.returncode == 0, result.stderr
    evidence = json.loads(result.stdout)
    assert evidence == {
        "kind": "wheel",
        "migration_directory": True,
        "name": wheel.name,
        "schema_origin": "yoke_core/domain/schema_init.py",
        "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
    }


def test_selected_wheel_never_falls_back_to_checkout_for_missing_schema(
    tmp_path: Path,
) -> None:
    wheel = _engine_wheel(tmp_path, include_schema=False)

    result = _activate_in_clean_process(wheel)

    assert result.returncode != 0
    assert "selected engine wheel cannot import schema_init" in result.stderr


def _activate_in_clean_process(wheel: Path) -> subprocess.CompletedProcess[str]:
    script = (
        "import json\n"
        "from pathlib import Path\n"
        "from runtime.api.tools.preflight_fleet_migrations import "
        "_activate_engine_artifact\n"
        f"artifact = _activate_engine_artifact({str(wheel)!r})\n"
        "from yoke_core.domain import schema_init\n"
        "evidence = artifact.evidence()\n"
        "evidence['migration_directory'] = "
        "Path(schema_init.__file__).with_name('migrations').is_dir()\n"
        "print(json.dumps(evidence, sort_keys=True))\n"
    )
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _engine_wheel(root: Path, *, include_schema: bool) -> Path:
    wheel = root / "yoke_core-1.0-py3-none-any.whl"
    members = {
        "yoke_core/__init__.py": "",
        "yoke_core/domain/__init__.py": "",
        "yoke_core/domain/migrations/__init__.py": "",
    }
    if include_schema:
        members["yoke_core/domain/schema_init.py"] = "ARTIFACT_ONLY = True\n"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, body in members.items():
            archive.writestr(name, body)
    return wheel
