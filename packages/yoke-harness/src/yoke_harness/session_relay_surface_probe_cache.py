"""Disk-backed last-known-good state for relay surface probes."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Callable, Mapping, Sequence

from yoke_harness.session_relay_schedule import relay_state_dir
from yoke_harness.session_relay_surface_probes import (
    CLI_SURFACE_PROBES,
    KNOWN_SURFACE_PROBES,
    SurfaceProbeResult,
    probe_cli_surface,
    probe_surface,
    probe_surfaces,
)


SURFACE_VERSION_MAX_AGE_SECONDS = 15 * 60
SURFACE_PROBE_CACHE_FILE_NAME = "surface-probes.json"
SURFACE_VERSION_PROBE_BUDGET_SECONDS = 1.0


@dataclass(frozen=True)
class SurfaceVersionObservation:
    """One reader's answer for a surface version, and how it was reached.

    ``source`` is ``cache`` (a fresh shared observation), ``probe`` (this
    reader ran the surface's own executable), ``cache_fallback`` (the probe
    failed and the newest recorded version answered instead), or ``none``.
    ``reason`` names the cause whenever the answer is absent or stale.
    """

    surface: str
    version: str | None
    source: str
    reason: str | None


def _cache_path(state_dir: Path | None) -> Path:
    return (state_dir or relay_state_dir()) / SURFACE_PROBE_CACHE_FILE_NAME


def _read_cache(state_dir: Path | None = None) -> dict[str, object]:
    try:
        payload = json.loads(_cache_path(state_dir).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {"schema_version": 1, "surfaces": {}}
    surfaces = payload.get("surfaces") if isinstance(payload, dict) else None
    return {
        "schema_version": 1,
        "surfaces": dict(surfaces) if isinstance(surfaces, Mapping) else {},
    }


def _write_cache(document: Mapping[str, object], state_dir: Path | None) -> None:
    path = _cache_path(state_dir)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(document, sort_keys=True), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def update_surface_probe_cache(
    results: Sequence[SurfaceProbeResult],
    *,
    state_dir: Path | None = None,
    annotation: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Record each probe attempt, successful or not, on its surface entry.

    ``annotation`` carries the reading caller's own verdict — which source
    ultimately answered, and why — so an empty observation names its cause
    on the surface operators already read instead of vanishing.
    """
    document = _read_cache(state_dir)
    surfaces = dict(document["surfaces"])
    for result in results:
        previous = surfaces.get(result.surface)
        entry = dict(previous) if isinstance(previous, Mapping) else {}
        entry.update(
            {
                "latest_verdict": result.verdict,
                "latest_error": result.error,
                "latest_duration_ms": result.duration_ms,
                "latest_attempt_at": result.observed_at,
            }
        )
        entry.update(dict(annotation or {}))
        if result.verdict == "ok" and result.version:
            entry["last_good_version"] = result.version
            entry["last_good_at"] = result.observed_at
        surfaces[result.surface] = entry
    document = {"schema_version": 1, "surfaces": surfaces}
    _write_cache(document, state_dir)
    return document


def _last_good_version(entry: Mapping[str, object]) -> str | None:
    """Return the newest version this surface ever reported, at any age."""
    version = entry.get("last_good_version")
    return version if isinstance(version, str) and version.strip() else None


def _last_good(
    entry: Mapping[str, object], now: float
) -> tuple[str | None, int | None]:
    version = _last_good_version(entry)
    try:
        age = max(0, round(now - float(entry.get("last_good_at"))))
    except (TypeError, ValueError):
        return None, None
    if version is None:
        return None, age
    return (version if age <= SURFACE_VERSION_MAX_AGE_SECONDS else None), age


def cached_surface_versions(
    *, state_dir: Path | None = None, now: float | None = None
) -> dict[str, str]:
    current = time.time() if now is None else now
    surfaces = _read_cache(state_dir)["surfaces"]
    versions: dict[str, str] = {}
    for surface, raw in surfaces.items():
        if isinstance(raw, Mapping):
            version, _age = _last_good(raw, current)
            if version:
                versions[str(surface)] = version
    return versions


def _diagnostics(
    results: Sequence[SurfaceProbeResult],
    document: Mapping[str, object],
    now: float,
) -> tuple[dict[str, object], ...]:
    surfaces = document.get("surfaces")
    entries = surfaces if isinstance(surfaces, Mapping) else {}
    diagnostics = []
    for result in results:
        raw = entries.get(result.surface)
        entry = raw if isinstance(raw, Mapping) else {}
        advertised, age = _last_good(entry, now)
        stale = bool(advertised and result.verdict != "ok")
        if stale:
            cache_state = "stale"
        elif result.verdict == "ok":
            cache_state = "fresh"
        elif age is not None and age > SURFACE_VERSION_MAX_AGE_SECONDS:
            cache_state = "expired"
        else:
            cache_state = "absent"
        diagnostics.append(
            {
                **result.to_dict(),
                "advertised_version": advertised,
                "cache_state": cache_state,
                "stale": stale,
                "stale_age_seconds": age if advertised else None,
            }
        )
    return tuple(diagnostics)


def refresh_surface_probe_cache(
    surface: str | None = None,
    *,
    state_dir: Path | None = None,
    probe: Callable[[str], SurfaceProbeResult] = probe_surface,
    now: float | None = None,
) -> tuple[dict[str, object], ...]:
    selected = (surface,) if surface else KNOWN_SURFACE_PROBES
    results = probe_surfaces(selected, probe=probe)
    document = update_surface_probe_cache(results, state_dir=state_dir)
    return _diagnostics(results, document, time.time() if now is None else now)


def _cached_version(
    surface: str,
    state_dir: Path | None,
    now: float | None,
) -> tuple[str | None, str | None]:
    """Return this surface's fresh cached version, or why there was none."""
    try:
        return cached_surface_versions(state_dir=state_dir, now=now).get(surface), None
    except Exception as exc:  # noqa: BLE001 - an unreachable cache is diagnosed
        return None, f"shared probe cache was unreadable: {type(exc).__name__}: {exc}"


def _cache_fallback_version(
    surface: str,
    state_dir: Path | None,
) -> tuple[str | None, str | None]:
    """Return the newest version this surface ever reported, at any age."""
    try:
        entry = _read_cache(state_dir)["surfaces"].get(surface)
    except Exception as exc:  # noqa: BLE001 - see _cached_version
        return None, f"shared probe cache was unreadable: {type(exc).__name__}: {exc}"
    if not isinstance(entry, Mapping):
        return None, f"shared probe cache holds no entry for surface {surface!r}"
    version = _last_good_version(entry)
    if version is None:
        return None, f"surface {surface!r} has never reported a version"
    return version, None


def bounded_surface_probe(
    surface: str,
    *,
    timeout: float = SURFACE_VERSION_PROBE_BUDGET_SECONDS,
) -> SurfaceProbeResult:
    """Ask one surface for its version without exceeding a caller's budget."""
    command = CLI_SURFACE_PROBES.get(surface)
    if command:
        return probe_cli_surface(surface, command, timeout=timeout)
    return probe_surface(surface)


def _record(
    result: SurfaceProbeResult,
    observation: SurfaceVersionObservation,
    state_dir: Path | None,
) -> None:
    """Write one attempt and the verdict it produced onto the shared cache."""
    try:
        update_surface_probe_cache(
            (result,),
            state_dir=state_dir,
            annotation={
                "last_version_source": observation.source,
                "last_version_reason": observation.reason,
            },
        )
    except Exception:  # noqa: BLE001 - an unwritable cache loses only the record
        pass


def observe_surface_version(
    surface: str | None,
    *,
    state_dir: Path | None = None,
    timeout: float = SURFACE_VERSION_PROBE_BUDGET_SECONDS,
    now: float | None = None,
) -> SurfaceVersionObservation:
    """Answer what version a surface runs, and say how the answer was reached.

    Resolution order: a fresh shared-cache observation, then a live probe
    under ``timeout``, then the newest version the shared cache ever recorded
    for this surface at any age. The last step exists because an empty
    version satisfies no declared floor, so writing one turns a momentarily
    unobservable surface into a permanently unqualified one; a stale-but-real
    version is marked ``cache_fallback`` rather than passed off as observed.

    Every attempt — successful or not — lands on the surface's shared-cache
    entry with the source and named reason, so an empty answer is diagnosable
    from the same file every other reader already consults.
    """
    name = str(surface or "").strip()
    if not name:
        return SurfaceVersionObservation("", None, "none", "no surface was named")
    cached, cache_reason = _cached_version(name, state_dir, now)
    if cached:
        return SurfaceVersionObservation(name, cached, "cache", None)
    result = bounded_surface_probe(name, timeout=timeout)
    if result.verdict == "ok" and result.version:
        observation = SurfaceVersionObservation(name, result.version, "probe", None)
        _record(result, observation, state_dir)
        return observation
    probe_reason = f"probe {result.verdict}: {result.error or 'no version reported'}"
    fallback, fallback_reason = _cache_fallback_version(name, state_dir)
    reasons = [reason for reason in (cache_reason, probe_reason) if reason]
    if fallback:
        observation = SurfaceVersionObservation(
            name, fallback, "cache_fallback", "; ".join(reasons)
        )
    else:
        reasons.append(fallback_reason or "")
        observation = SurfaceVersionObservation(
            name, None, "none", "; ".join(reason for reason in reasons if reason)
        )
    _record(result, observation, state_dir)
    return observation


def observed_surface_version(
    surface: str | None,
    *,
    state_dir: Path | None = None,
    timeout: float = SURFACE_VERSION_PROBE_BUDGET_SECONDS,
    now: float | None = None,
) -> str | None:
    """Return the version the surface's own executable reports, or ``None``.

    Every reader of a machine's surface version answers from here: the relay
    heartbeat that advertises the machine, the launch preview that quotes that
    advertisement, and the registration of each session running on it. A
    launcher's environment hand-off is deliberately not a source, because it
    describes what some earlier process believed rather than what this one
    runs, and a pooled or pre-warmed harness process inherits that belief long
    after the binary underneath it has been replaced.

    ``None`` means no source could name a version — an unknown surface, a
    surface with no probe, or a first-ever observation that failed — and
    :func:`observe_surface_version` carries the reason for callers that
    report it.
    """
    return observe_surface_version(
        surface, state_dir=state_dir, timeout=timeout, now=now
    ).version


__all__ = [
    "SURFACE_VERSION_MAX_AGE_SECONDS",
    "SURFACE_VERSION_PROBE_BUDGET_SECONDS",
    "SurfaceVersionObservation",
    "bounded_surface_probe",
    "cached_surface_versions",
    "observe_surface_version",
    "observed_surface_version",
    "refresh_surface_probe_cache",
    "update_surface_probe_cache",
]
