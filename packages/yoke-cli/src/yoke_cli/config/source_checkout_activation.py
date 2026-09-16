"""Activate a Yoke source checkout without depending on its installed wheel."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, TypeVar

from yoke_cli.config import editable_install
from yoke_cli.project_install.files import MODE_SOURCE_LINK

_Error = TypeVar("_Error", bound=Exception)
_EDITABLE_PACKAGES = ("yoke-contracts", "yoke-core", "yoke-cli", "yoke-harness")
_SOURCE_LINK_SNIPPET = (
    "import json, sys\n"
    "from pathlib import Path\n"
    "from yoke_core.domain.project_install_source_link import install_source_link\n"
    "print(json.dumps("
    "install_source_link(Path(sys.argv[1]), operation=sys.argv[2]), default=str))\n"
)


def install_source_checkout(
    root: Path,
    *,
    editable: bool = True,
    error_type: type[_Error] = RuntimeError,
) -> dict[str, Any]:
    """Install the source-link layer and optionally repoint the tool venv."""
    provisioned: dict[str, Any] = {"strategy": MODE_SOURCE_LINK}
    if editable:
        provisioned["editable_install"] = _run_editable_install(
            root,
            error_type=error_type,
        )
    source_link = _run_source_link_subprocess(root, error_type=error_type)
    provisioned["source_link"] = source_link
    provisioned["machine_config_newly_registered"] = bool(
        source_link.get("machine_config_newly_registered")
    )
    provisioned["warnings"] = list(source_link.get("warnings") or [])
    return provisioned


def _run_editable_install(
    root: Path,
    *,
    error_type: type[_Error] = RuntimeError,
) -> dict[str, Any]:
    packages = [root / "packages" / name for name in _EDITABLE_PACKAGES]
    missing = [
        str(path) for path in packages if not (path / "pyproject.toml").is_file()
    ]
    if missing:
        raise error_type(
            "editable install package roots are missing: " + ", ".join(missing)
        )
    loader_source_text = editable_install.loader_source()
    uv = _find_uv()
    command = (
        [uv, "pip", "install", "--python", sys.executable]
        if uv is not None
        else [sys.executable, "-m", "pip", "install"]
    )
    for package in packages:
        command.extend(["-e", str(package)])
    result = subprocess.run(
        command,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise error_type(
            f"editable install failed: {result.stderr.strip() or result.stdout.strip()}"
        )
    swap = editable_install.swap_to_config_driven(
        editable_install.site_packages_dir(),
        repo_root=root,
        loader_source_text=loader_source_text,
    )
    return {
        "ok": True,
        "command": command,
        "packages": [str(package) for package in packages],
        "config_driven_pth": swap,
    }


def _find_uv() -> str | None:
    found = shutil.which("uv")
    if found:
        return found
    fallback = Path.home() / ".local" / "bin" / "uv"
    return str(fallback) if fallback.is_file() else None


def _checkout_pythonpath(root: Path) -> str:
    parts = [str(root / "packages" / name / "src") for name in _EDITABLE_PACKAGES]
    parts.append(str(root))
    existing = os.environ.get("PYTHONPATH", "")
    if existing:
        parts.append(existing)
    return os.pathsep.join(parts)


def _run_source_link_subprocess(
    root: Path,
    *,
    error_type: type[_Error] = RuntimeError,
) -> dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONPATH"] = _checkout_pythonpath(root)
    result = subprocess.run(
        [sys.executable, "-c", _SOURCE_LINK_SNIPPET, str(root), "dev.setup"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=env,
    )
    if result.returncode != 0:
        raise error_type(
            "source-link setup failed: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise error_type(
            f"source-link setup returned unreadable output: {result.stdout!r}"
        ) from exc


def run_editable_install_step(
    root: Path,
    *,
    error_type: type[_Error] = RuntimeError,
) -> dict[str, Any]:
    """Run the deferred editable install and return a printable outcome."""
    try:
        editable = _run_editable_install(root, error_type=error_type)
    except error_type as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "editable_install": editable}


__all__ = ["install_source_checkout", "run_editable_install_step"]
