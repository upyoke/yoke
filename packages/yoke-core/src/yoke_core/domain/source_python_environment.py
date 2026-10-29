"""Bind a checkout's locked Python environment, syncing drift to its own lock.

Source verification and candidate Command cases share the same declaration
and uv check. A drifted ``.venv`` is synced to the checkout's unchanged lock
unless the caller asks for a check only; candidate QA never repairs.
Installed control-plane launchers never call this resolver.
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from yoke_contracts.qa_case_environment import COMMAND_CASE_CANDIDATE_TREE_ENV
from yoke_contracts.refusal_recovery import compose_refusal
from yoke_contracts.uv_project import UV_EXECUTABLE, is_uv_project

from yoke_core.domain.qa_environment_declaration import (
    TestEnvironmentDeclaration,
    load_declaration,
)

QA_SOURCE_ENVIRONMENT_ENV = "YOKE_QA_SOURCE_ENVIRONMENT"


class SourceEnvironmentRefusal(ValueError):
    """The selected checkout cannot supply truthful source verification."""


def venv_python(prefix: Path) -> Path:
    """The interpreter path inside the virtual environment at *prefix*."""
    return prefix / ("Scripts/python.exe" if os.name == "nt" else "bin/python3")


@dataclass(frozen=True)
class SourcePythonEnvironment:
    python: str
    env: dict[str, str]
    evidence: dict


def _declaration(root: Path, env: Mapping[str, str]) -> TestEnvironmentDeclaration:
    snapshot = env.get(QA_SOURCE_ENVIRONMENT_ENV)
    candidate = env.get(COMMAND_CASE_CANDIDATE_TREE_ENV)
    if not snapshot or not candidate:
        return load_declaration(
            project=env.get("YOKE_PROJECT"), checkout=root, strict=True
        )
    try:
        tree = json.loads(candidate)
        receipt = json.loads(snapshot)
        if (
            not isinstance(tree, dict)
            or not isinstance(receipt, dict)
            or tree.get("root") != str(root)
            or receipt.get("root") != str(root)
        ):
            raise ValueError("declaration does not belong to the selected candidate")
        raw = receipt["declaration"]
        if (
            not isinstance(raw, dict)
            or set(raw) != {"project", "uv_project", "extras", "groups"}
            or not isinstance(raw["project"], str)
            or not raw["project"]
            or not isinstance(raw["uv_project"], str)
            or any(
                not isinstance(raw[key], list)
                or any(not isinstance(value, str) or not value for value in raw[key])
                for key in ("extras", "groups")
            )
        ):
            raise ValueError("invalid runner declaration")
        return TestEnvironmentDeclaration(
            project=raw["project"],
            uv_project=raw["uv_project"],
            extras=tuple(raw["extras"]),
            groups=tuple(raw["groups"]),
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise SourceEnvironmentRefusal(
            "SOURCE-ENVIRONMENT-QA-DECLARATION: invalid candidate environment "
            "handoff. Rerun the same QA case through its candidate-bound runner "
            "to regenerate the declaration; preserve its candidate environment variables."
        ) from exc


def _uv(project: Path, env: dict[str, str], argv: list[str], timeout: int):
    return subprocess.run(
        argv,
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def resolve(
    root: Path, env: Mapping[str, str], *, repair: bool = True
) -> SourcePythonEnvironment:
    """Check the declared lock and interpreter; sync a drifted environment.

    ``repair=False`` only checks, so a drifted environment refuses instead.
    """
    root = root.resolve()
    try:
        declaration = _declaration(root, env)
    except SourceEnvironmentRefusal:
        raise
    except Exception as exc:
        raise SourceEnvironmentRefusal(
            f"SOURCE-ENVIRONMENT-DECLARATION: could not read the checkout's QA "
            f"environment declaration ({type(exc).__name__}). Restore the "
            "control-plane connection and select the project with --project, "
            "YOKE_PROJECT, or a registered checkout mapping, then retry the same command."
        ) from exc
    project = (root / (declaration.uv_project or ".")).resolve()
    flags = declaration.selection_flags()
    sync = ["uv", "sync", "--locked", "--offline", "--no-python-downloads", *flags]
    recovery = (
        f"In {shlex.quote(str(project))}, run `{shlex.join(sync)}` and retry "
        "the same source command."
    )

    def refuse(reason: str, detail: str, fix: str = recovery) -> None:
        raise SourceEnvironmentRefusal(
            compose_refusal(f"{reason}: {detail}.", recovery=fix)
        )

    if not project.is_relative_to(root) or not is_uv_project(project):
        refuse(
            "SOURCE-ENVIRONMENT-LOCK-MISSING", f"no declared locked project in {root}"
        )
    prefix = project / ".venv"
    python = venv_python(prefix)
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
    # An ambient environment cannot redirect uv to main or disable groups,
    # so a sync only ever writes this checkout's own .venv.
    clean["UV_PROJECT_ENVIRONMENT"] = str(prefix)
    repaired: list[str] = []
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
        check = [UV_EXECUTABLE, "sync", "--check", *sync[2:]]
        if _uv(project, clean, check, 30).returncode:
            if _uv(
                project, clean, [UV_EXECUTABLE, "lock", "--check", "--offline"], 30
            ).returncode:
                refuse(
                    "SOURCE-ENVIRONMENT-LOCK-STALE",
                    f"uv.lock in {project} does not match its pyproject.toml",
                    f"In {shlex.quote(str(project))}, update the lock deliberately "
                    "in this claimed checkout: `uv lock`, then retry the same "
                    "source command.",
                )
            if not repair:
                refuse(
                    "SOURCE-ENVIRONMENT-OUT-OF-DATE",
                    f"{prefix} does not match the lock in {project}",
                )
            synced = _uv(project, clean, [UV_EXECUTABLE, *sync[1:]], 600)
            if synced.returncode or _uv(project, clean, check, 30).returncode:
                lines = synced.stderr.strip().splitlines() or ["no stderr"]
                refuse(
                    "SOURCE-ENVIRONMENT-SYNC-FAILED",
                    f"`{shlex.join(sync)}` exited {synced.returncode} and left "
                    f"{prefix} out of date: {lines[-1]}",
                )
            repaired = sync
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
            "declaration": {
                "project": declaration.project,
                "uv_project": declaration.uv_project,
                "extras": list(declaration.extras),
                "groups": list(declaration.groups),
            },
            "project": str(project),
            **facts,
            "extras": list(declaration.extras),
            "groups": list(declaration.groups),
            "lock_sha256": hashlib.sha256(
                (project / "uv.lock").read_bytes()
            ).hexdigest(),
            **({"repaired": repaired} if repaired else {}),
        },
    )
