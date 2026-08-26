"""Live relay surface probes and native executable resolution."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import time
from typing import Callable, Sequence

from yoke_contracts.harness_cli_manifest import (
    HARNESS_CLI_MANIFESTS,
    harness_cli_probe_commands,
)

SURFACE_PROBE_TIMEOUT_SECONDS = 30.0
_VERSION_PATTERN = re.compile(r"\d+(?:\.\d+)+(?:[-+._A-Za-z0-9]*)?")
CLI_SURFACE_PROBES = harness_cli_probe_commands()
APP_SURFACE_PROBES = {
    "claude-desktop": Path("/Applications/Claude.app/Contents/Info.plist"),
    "codex-desktop": Path("/Applications/ChatGPT.app/Contents/Info.plist"),
    "cursor-desktop": Path("/Applications/Cursor.app/Contents/Info.plist"),
}
_CLI_FALLBACKS = {
    manifest.executable: tuple(Path(raw) for raw in manifest.bundled_candidates)
    for manifest in HARNESS_CLI_MANIFESTS
    if manifest.bundled_candidates
}
KNOWN_SURFACE_PROBES = tuple((*CLI_SURFACE_PROBES, *APP_SURFACE_PROBES))


@dataclass(frozen=True)
class SurfaceProbeResult:
    surface: str
    source: str
    verdict: str
    version: str | None
    duration_ms: int
    error: str | None
    observed_at: float

    def to_dict(self) -> dict[str, object]:
        return {
            "surface": self.surface,
            "source": self.source,
            "verdict": self.verdict,
            "version": self.version,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "observed_at": self.observed_at,
        }


@dataclass(frozen=True)
class ResolvedNativeCli:
    """Which executable served a probe or launch, and by which route."""

    path: str
    source: str


def _version_token(text: str) -> str | None:
    matched = _VERSION_PATTERN.search(text)
    return matched.group(0).rstrip("-+._") if matched else None


def resolve_native_cli_source(command_name: str) -> ResolvedNativeCli | None:
    """Resolve a native CLI exactly as the surface-version probe finds it.

    The advertised probe and launch transport must resolve the same executable.
    The source distinguishes a standalone install from a bundled desktop copy
    so diagnostics can identify which independently released build ran.
    """
    if os.sep in command_name:
        candidate = Path(command_name)
        return (
            ResolvedNativeCli(command_name, "explicit")
            if candidate.is_file() and os.access(candidate, os.X_OK)
            else None
        )
    found = shutil.which(command_name)
    if found:
        return ResolvedNativeCli(found, "path")
    for fallback in _CLI_FALLBACKS.get(command_name, ()):
        if fallback.is_file() and os.access(fallback, os.X_OK):
            return ResolvedNativeCli(str(fallback), "bundled")
    return None


def resolve_native_cli(command_name: str) -> str | None:
    """Return only the executable for callers that do not report provenance."""
    resolved = resolve_native_cli_source(command_name)
    return resolved.path if resolved else None


def _duration_ms(started_at: float, monotonic: Callable[[], float]) -> int:
    return max(0, round((monotonic() - started_at) * 1000))


def _bounded_error(completed: subprocess.CompletedProcess[str]) -> str:
    text = (completed.stderr or completed.stdout or "").strip().splitlines()
    detail = text[0][:160] if text else "no output"
    return f"exit {completed.returncode}: {detail}"


def probe_cli_surface(
    surface: str,
    command: tuple[str, ...],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    timeout: float = SURFACE_PROBE_TIMEOUT_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
    clock: Callable[[], float] = time.time,
) -> SurfaceProbeResult:
    started_at = monotonic()
    observed_at = clock()
    executable = resolve_native_cli(command[0])
    if not executable:
        return SurfaceProbeResult(
            surface,
            "exec",
            "missing",
            None,
            _duration_ms(started_at, monotonic),
            f"executable {command[0]!r} was not found",
            observed_at,
        )
    try:
        completed = runner(
            [executable, *command[1:]],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return SurfaceProbeResult(
            surface,
            "exec",
            "timeout",
            None,
            _duration_ms(started_at, monotonic),
            f"timed out after {timeout:g}s",
            observed_at,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return SurfaceProbeResult(
            surface,
            "exec",
            "error",
            None,
            _duration_ms(started_at, monotonic),
            f"{type(exc).__name__}: {exc}",
            observed_at,
        )
    if completed.returncode != 0:
        return SurfaceProbeResult(
            surface,
            "exec",
            "error",
            None,
            _duration_ms(started_at, monotonic),
            _bounded_error(completed),
            observed_at,
        )
    version = _version_token((completed.stdout or completed.stderr or "").strip())
    verdict = "ok" if version else "invalid_output"
    return SurfaceProbeResult(
        surface,
        "exec",
        verdict,
        version,
        _duration_ms(started_at, monotonic),
        None if version else "version output contained no version token",
        observed_at,
    )


def probe_app_surface(
    surface: str,
    path: Path,
    *,
    monotonic: Callable[[], float] = time.monotonic,
    clock: Callable[[], float] = time.time,
) -> SurfaceProbeResult:
    started_at = monotonic()
    observed_at = clock()
    try:
        with path.open("rb") as handle:
            payload = plistlib.load(handle)
    except FileNotFoundError:
        verdict, version, error = "missing", None, f"{path} was not found"
    except (OSError, ValueError, plistlib.InvalidFileException) as exc:
        verdict, version, error = "error", None, f"{type(exc).__name__}: {exc}"
    else:
        version = _version_token(
            str(payload.get("CFBundleShortVersionString") or "").strip()
        )
        verdict = "ok" if version else "invalid_output"
        error = None if version else "bundle contained no version token"
    return SurfaceProbeResult(
        surface,
        "file",
        verdict,
        version,
        _duration_ms(started_at, monotonic),
        error,
        observed_at,
    )


def probe_surface(surface: str) -> SurfaceProbeResult:
    if surface in CLI_SURFACE_PROBES:
        return probe_cli_surface(surface, CLI_SURFACE_PROBES[surface])
    if surface in APP_SURFACE_PROBES:
        return probe_app_surface(surface, APP_SURFACE_PROBES[surface])
    return SurfaceProbeResult(
        surface,
        "unknown",
        "unsupported",
        None,
        0,
        f"unknown relay surface {surface!r}",
        time.time(),
    )


def _probe_safely(
    surface: str,
    probe: Callable[[str], SurfaceProbeResult],
) -> SurfaceProbeResult:
    started_at = time.monotonic()
    observed_at = time.time()
    try:
        return probe(surface)
    except Exception as exc:
        source = (
            "exec"
            if surface in CLI_SURFACE_PROBES
            else "file"
            if surface in APP_SURFACE_PROBES
            else "unknown"
        )
        return SurfaceProbeResult(
            surface,
            source,
            "error",
            None,
            _duration_ms(started_at, time.monotonic),
            f"{type(exc).__name__}: {exc}",
            observed_at,
        )


def probe_surfaces(
    surfaces: Sequence[str] | None = None,
    *,
    probe: Callable[[str], SurfaceProbeResult] = probe_surface,
) -> tuple[SurfaceProbeResult, ...]:
    selected = tuple(surfaces or KNOWN_SURFACE_PROBES)
    if not selected:
        return ()
    with ThreadPoolExecutor(max_workers=len(selected)) as executor:
        return tuple(
            executor.map(lambda surface: _probe_safely(surface, probe), selected)
        )


__all__ = [
    "APP_SURFACE_PROBES",
    "CLI_SURFACE_PROBES",
    "KNOWN_SURFACE_PROBES",
    "SURFACE_PROBE_TIMEOUT_SECONDS",
    "ResolvedNativeCli",
    "SurfaceProbeResult",
    "probe_app_surface",
    "probe_cli_surface",
    "probe_surface",
    "probe_surfaces",
    "resolve_native_cli",
    "resolve_native_cli_source",
]
