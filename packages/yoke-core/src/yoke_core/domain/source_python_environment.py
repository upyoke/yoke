"""Validate a checkout's locked Python environment without changing it.

Source verification and candidate Command cases share the same declaration
and uv check. Installed control-plane launchers never call this resolver.
"""

from __future__ import annotations

import json
import hashlib
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from yoke_contracts.uv_project import UV_EXECUTABLE, is_uv_project
from yoke_core.domain.qa_environment_declaration import load_declaration


class SourceEnvironmentRefusal(ValueError):
    """The selected checkout cannot supply truthful source verification."""


@dataclass(frozen=True)
class SourcePythonEnvironment:
    python: str
    env: dict[str, str]
    evidence: dict


def resolve(root: Path, env: Mapping[str, str]) -> SourcePythonEnvironment:
    """Check the declared lock, environment, and interpreter; never sync."""
    root = root.resolve()
    try:
        declaration = load_declaration(checkout=root, strict=True)
    except Exception as exc:
        raise SourceEnvironmentRefusal(
            f"SOURCE-ENVIRONMENT-DECLARATION: could not read the checkout's QA "
            f"environment declaration ({type(exc).__name__}). Restore the "
            "control-plane connection and project mapping, then retry the same command."
        ) from exc
    project = (root / (declaration.uv_project or ".")).resolve()
    flags = declaration.selection_flags()
    recovery = (
        f"In {shlex.quote(str(project))}, run "
        f"`uv sync --locked {' '.join(map(shlex.quote, flags))}` and retry "
        "the same source command. If the lock is stale, update it deliberately "
        "in this claimed checkout first; checks never rewrite it."
    )

    def refuse(reason: str, detail: str) -> None:
        raise SourceEnvironmentRefusal(f"{reason}: {detail}. Recovery: {recovery}")

    if not project.is_relative_to(root) or not is_uv_project(project):
        refuse(
            "SOURCE-ENVIRONMENT-LOCK-MISSING", f"no declared locked project in {root}"
        )
    prefix = project / ".venv"
    python = prefix / ("Scripts/python.exe" if os.name == "nt" else "bin/python3")
    if not python.is_file() or prefix.resolve().parent != project:
        refuse(
            "SOURCE-ENVIRONMENT-MISSING",
            f"checkout-owned environment missing at {prefix}",
        )
    clean = {key: value for key, value in env.items() if not key.startswith("UV_")}
    clean.pop("PYTHONHOME", None)
    clean["PYTHONNOUSERSITE"] = "1"
    clean["VIRTUAL_ENV"] = str(prefix)
    clean["PATH"] = str(python.parent) + os.pathsep + clean.get("PATH", "")
    # An ambient environment cannot redirect uv to main or disable groups.
    clean["UV_PROJECT_ENVIRONMENT"] = str(prefix)
    try:
        # A synchronized package set alone does not prove .python-version.
        # Delegate every supported Python request format to uv, without letting
        # it provision another interpreter or use that interpreter for checks.
        requested = subprocess.run(
            [UV_EXECUTABLE, "python", "find", "--offline", "--no-python-downloads"],
            cwd=project,
            env=clean,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if (
            requested.returncode
            or not requested.stdout.strip()
            or Path(requested.stdout.strip()).resolve() != python.resolve()
        ):
            refuse(
                "SOURCE-ENVIRONMENT-OUT-OF-DATE",
                f"declared Python request does not select the interpreter at {python}",
            )
        checked = subprocess.run(
            [
                UV_EXECUTABLE,
                "sync",
                "--check",
                "--locked",
                "--offline",
                "--no-python-downloads",
                *flags,
            ],
            cwd=project,
            env=clean,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if checked.returncode:
            refuse(
                "SOURCE-ENVIRONMENT-OUT-OF-DATE",
                f"uv lock/environment check failed in {project}",
            )
        identity = subprocess.run(
            [
                str(python),
                "-c",
                "import json,sys; print(json.dumps({'python':sys.executable,"
                "'prefix':sys.prefix,'version':sys.version.split()[0]}))",
            ],
            cwd=root,
            env=clean,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        facts = json.loads(identity.stdout) if identity.returncode == 0 else {}
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        if isinstance(exc, SourceEnvironmentRefusal):
            raise
        refuse("SOURCE-ENVIRONMENT-CHECK-FAILED", type(exc).__name__)
    if (
        not isinstance(facts, dict)
        or Path(facts.get("prefix", "/")).resolve() != prefix.resolve()
    ):
        refuse("SOURCE-ENVIRONMENT-IDENTITY", f"Python does not belong to {prefix}")
    config = prefix / "pyvenv.cfg"
    if (
        not config.is_file()
        or "include-system-site-packages=true"
        in config.read_text().lower().replace(" ", "")
    ):
        refuse(
            "SOURCE-ENVIRONMENT-IDENTITY", "environment permits ambient system packages"
        )
    return SourcePythonEnvironment(
        str(python),
        clean,
        {
            "root": str(root),
            "project": str(project),
            **facts,
            "extras": list(declaration.extras),
            "groups": list(declaration.groups),
            "lock_sha256": hashlib.sha256(
                (project / "uv.lock").read_bytes()
            ).hexdigest(),
        },
    )
