"""Converge every machine launcher surface onto the canonical login-shell shim.

The canonical shim is ``$XDG_BIN_HOME/yoke`` or ``~/.local/bin/yoke``.
Shadow installs on PATH (uv-tool shims, pipx, stray venv binaries) are
moved aside with a restore path — never deleted. The uv tool tree itself
stays intact.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Mapping, Optional

from yoke_cli.config.path_state_contract import tool_bin_dir
from yoke_core.tools.install_yoke_launcher_cleanup import (
    quarantine_shadow_launcher,
)
from yoke_core.tools.install_yoke_launcher_core import (
    InstallError,
    LAUNCHER_FILENAME,
    refuse_foreign_binary,
    verify_repo_root,
    write_launcher,
)


LAUNCHER_PROBE_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class ShadowInstall:
    path: Path
    kind: str


@dataclass
class SweepReport:
    canonical: Path
    written: bool = False
    quarantined: List[Path] = field(default_factory=list)
    shadows: List[ShadowInstall] = field(default_factory=list)


def canonical_shim_path(env: Optional[Mapping[str, str]] = None) -> Path:
    """Return the login-shell shim path this machine must resolve."""
    return Path(tool_bin_dir(env)) / LAUNCHER_FILENAME


def classify_shadow(path: Path) -> str:
    """Name the install kind for a non-canonical ``yoke`` binary."""
    text = str(path)
    if "/uv/tools/" in text or "/.local/share/uv/tools/" in text:
        return "uv_tool"
    if "/pipx/" in text or "/.local/pipx/" in text:
        return "pipx"
    if "/.venv/bin/" in text or "/venv/bin/" in text:
        return "venv"
    return "path_entry"


def enumerate_shadow_installs(
    *,
    canonical: Optional[Path] = None,
    env: Optional[Mapping[str, str]] = None,
    extra_paths: Optional[List[Path]] = None,
) -> List[ShadowInstall]:
    """Find ``yoke`` binaries on PATH that are not the canonical shim."""
    environ = os.environ if env is None else env
    canonical_path = (canonical or canonical_shim_path(environ)).resolve()
    found: List[ShadowInstall] = []
    seen: set[Path] = set()
    entries = list(environ.get("PATH", "").split(os.pathsep))
    for extra in extra_paths or ():
        entries.append(str(extra.parent if extra.name == LAUNCHER_FILENAME else extra))
    for raw in entries:
        if not raw:
            continue
        candidate = Path(raw).expanduser() / LAUNCHER_FILENAME
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if not candidate.exists() or resolved in seen:
            continue
        seen.add(resolved)
        if resolved == canonical_path:
            continue
        found.append(ShadowInstall(path=candidate, kind=classify_shadow(resolved)))
    return found


def _candidate_interpreters(checkout: Path, home: Optional[Path]) -> List[Path]:
    """Return distinct launcher interpreters in machine-preference order."""
    raw_candidates: List[Path] = []
    if home is not None:
        raw_candidates.append(Path(home) / ".venv" / "bin" / "python3")
    raw_candidates.extend(
        [
            Path(checkout) / ".venv" / "bin" / "python3",
            Path(sys.executable),
        ]
    )

    candidates: List[Path] = []
    seen: set[Path] = set()
    for candidate in raw_candidates:
        invocation_path = Path(os.path.abspath(candidate.expanduser()))
        if invocation_path in seen or not invocation_path.is_file():
            continue
        seen.add(invocation_path)
        candidates.append(invocation_path)
    return candidates


def _render_launcher_candidate(
    target: Path,
    *,
    default_home: Path,
    interpreter: Path,
) -> Path:
    """Render the installable shim beside its eventual canonical path."""
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".candidate",
    )
    os.close(descriptor)
    candidate = Path(raw_path)
    try:
        write_launcher(
            candidate,
            default_home=default_home,
            python=interpreter,
        )
    except Exception:
        candidate.unlink(missing_ok=True)
        raise
    return candidate


def _launcher_probe_passes(candidate: Path, *, default_home: Path) -> bool:
    """Return whether the rendered launcher completes its version probe."""
    probe_env = os.environ.copy()
    probe_env["YOKE_HOME"] = str(default_home)
    probe_env.pop("PYTHONHOME", None)
    probe_env.pop("PYTHONPATH", None)
    try:
        subprocess.run(
            [str(candidate), "--version"],
            check=True,
            env=probe_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=LAUNCHER_PROBE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def repair_canonical_launcher(
    checkout: Path,
    *,
    home: Optional[Path] = None,
    force: bool = False,
    env: Optional[Mapping[str, str]] = None,
    stream=None,
) -> Path:
    """Write or repair the canonical shim against ``checkout``."""
    verify_repo_root(checkout)
    target = canonical_shim_path(env)
    if not target.is_symlink():
        refuse_foreign_binary(target, force=force)

    default_home = Path(home or checkout)
    interpreters = _candidate_interpreters(checkout, home)
    for interpreter in interpreters:
        candidate = _render_launcher_candidate(
            target,
            default_home=default_home,
            interpreter=interpreter,
        )
        if not _launcher_probe_passes(candidate, default_home=default_home):
            candidate.unlink(missing_ok=True)
            continue
        try:
            os.replace(candidate, target)
        except OSError as exc:
            candidate.unlink(missing_ok=True)
            raise InstallError(
                f"cannot atomically replace canonical launcher {target}: {exc}"
            ) from exc
        break
    else:
        raise InstallError(
            f"cannot repair canonical launcher {target}: "
            "no candidate interpreter passed the launcher --version probe."
        )

    if stream is not None:
        stream.write(f"Canonical launcher repaired: {target}\n")
    return target


def converge_machine(
    checkout: Path,
    *,
    home: Optional[Path] = None,
    force: bool = False,
    env: Optional[Mapping[str, str]] = None,
    extra_paths: Optional[List[Path]] = None,
    stream=None,
) -> SweepReport:
    """Write the canonical shim and quarantine every PATH shadow."""
    environ = os.environ if env is None else env
    target = repair_canonical_launcher(
        checkout, home=home, force=force, env=environ, stream=stream,
    )
    report = SweepReport(canonical=target, written=True)
    report.shadows = enumerate_shadow_installs(
        canonical=target, env=environ, extra_paths=extra_paths,
    )
    stamp = time.strftime("%Y%m%d%H%M%S")
    for shadow in report.shadows:
        quarantined = quarantine_shadow_launcher(
            shadow.path, stamp=stamp, stream=stream,
        )
        report.quarantined.append(quarantined)
    return report


__all__ = [
    "ShadowInstall",
    "SweepReport",
    "canonical_shim_path",
    "classify_shadow",
    "converge_machine",
    "enumerate_shadow_installs",
    "repair_canonical_launcher",
]
