"""What models one machine's installed harness surface will actually accept.

Availability is observed from the surface itself, never from a list compiled
when this code was written. A hardcoded catalog ages into a lie in both
directions at once: it withholds a model the account can already select, and
it offers one the vendor has retired. Both were live here — an installed
codex app-server published ``gpt-6-astra`` and ``gpt-5.3-codex-spark`` that
no static list named, and named ``gpt-5.4-mini`` with a retirement date the
same list called ``gpt-5.4``.

A reading is deliberately separate from anything researched about a model.
Price, tier and benchmark facts arrive on their own schedule, and a model
this machine can select right now stays selectable whether or not that
research exists yet.

Staleness is a first-class answer. A probe that fails leaves the models it
last saw in place and says the reading is ``stale`` with the reason — an
unreachable surface has not withdrawn its models, and reporting an empty
list would read as exactly that.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

#: Every surface a relay can report. Desktop and editor surfaces are listed
#: so their availability is answered explicitly rather than inferred from the
#: CLI that happens to share their vendor: shipping a CLI proves nothing
#: about what the desktop app on the same machine will accept.
NATIVE_MODEL_SURFACES = (
    "claude-cli",
    "claude-desktop",
    "claude-vscode",
    "codex-cli",
    "codex-desktop",
    "codex-vscode",
    "cursor-cli",
    "cursor-desktop",
)

#: ``ok`` — this reading came from the surface itself just now.
#: ``stale`` — the last attempt failed and these are the models last seen.
#: ``unsupported`` — Yoke declares no native listing route for this surface.
#: ``unknown`` — the surface has never answered, so nothing is known yet.
NATIVE_MODEL_STATUSES = frozenset({"ok", "stale", "unsupported", "unknown"})

#: A vendor that starts publishing per-variant tokens must not be able to
#: grow one machine row without bound. Cursor already publishes 211 rows —
#: one per base model, reasoning effort and speed variant — so the bound has
#: to clear a real listing by a wide margin or it becomes the thing that
#: hides available models. Reaching it is reported, never silent.
MAX_MODELS_PER_SURFACE = 256
TRUNCATED_REASON = "listing exceeded the per-surface bound and was truncated"
_STRING_MAX = 160

#: The reason a surface with no declared adapter reports. It names Yoke's own
#: registry rather than the vendor's capability, because an absent adapter is
#: the only fact observation actually establishes.
NO_ADAPTER_REASON = "no native model listing adapter is declared for this surface"


def _clip(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:_STRING_MAX] if text else None


def _without_empties(entry: dict[str, Any]) -> dict[str, Any]:
    """Drop the fields a vendor did not publish.

    Cursor lists 211 model tokens and publishes a replacement target for none
    of them; carrying six explicit nulls per row would be a third of the
    document saying nothing.
    """
    return {key: value for key, value in entry.items() if value or key == "model"}


def _efforts(raw: object) -> list[str]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    seen: dict[str, None] = {}
    for entry in raw:
        effort = _clip(entry)
        if effort:
            seen.setdefault(effort.lower(), None)
    return list(seen)


def native_model(
    model: str,
    *,
    description: str | None = None,
    reasoning_efforts: Sequence[str] = (),
    default_reasoning_effort: str | None = None,
    replaced_by: str | None = None,
    retires_at: str | None = None,
) -> dict[str, Any]:
    """One selectable model exactly as its surface published it."""
    return _without_empties(
        {
            "model": _clip(model) or "",
            "description": _clip(description),
            "reasoning_efforts": _efforts(reasoning_efforts),
            "default_reasoning_effort": _clip(default_reasoning_effort),
            "replaced_by": _clip(replaced_by),
            "retires_at": _clip(retires_at),
        }
    )


def models_reading(
    surface: str,
    models: Sequence[Mapping[str, Any]],
    *,
    source: str,
    observed_at: str,
) -> dict[str, Any]:
    """A live listing this surface answered, bounded and honest about it."""
    kept = [dict(model) for model in models[:MAX_MODELS_PER_SURFACE]]
    return {
        "surface": surface,
        "status": "ok",
        "reason": TRUNCATED_REASON if len(models) > len(kept) else None,
        "source": source,
        "observed_at": observed_at,
        "models": kept,
    }


def empty_reading(
    surface: str,
    status: str,
    reason: str,
    *,
    source: str = "",
    observed_at: str = "",
) -> dict[str, Any]:
    """A reading that names why it carries no models."""
    return {
        "surface": surface,
        "status": status if status in NATIVE_MODEL_STATUSES else "unknown",
        "reason": reason,
        "source": source,
        "observed_at": observed_at,
        "models": [],
    }


def stale_reading(
    previous: Mapping[str, Any] | None,
    surface: str,
    reason: str,
) -> dict[str, Any]:
    """Keep the models last seen and say the reading is no longer fresh.

    A surface that could not be reached has not withdrawn anything, so the
    previous list survives with its original ``observed_at``. Only a surface
    that never answered reports ``unknown``.
    """
    models = previous.get("models") if isinstance(previous, Mapping) else None
    if not isinstance(models, Sequence) or not models:
        return empty_reading(surface, "unknown", reason)
    return {
        "surface": surface,
        "status": "stale",
        "reason": reason,
        "source": str((previous or {}).get("source") or ""),
        "observed_at": str((previous or {}).get("observed_at") or ""),
        "models": [dict(model) for model in models if isinstance(model, Mapping)],
    }


def _sanitize_model(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    model = _clip(raw.get("model"))
    if not model:
        return None
    return _without_empties(
        {
            "model": model,
            "description": _clip(raw.get("description")),
            "reasoning_efforts": _efforts(raw.get("reasoning_efforts")),
            "default_reasoning_effort": _clip(raw.get("default_reasoning_effort")),
            "replaced_by": _clip(raw.get("replaced_by")),
            "retires_at": _clip(raw.get("retires_at")),
        }
    )


def _sanitize_models(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return []
    cleaned: list[dict[str, Any]] = []
    for entry in raw[:MAX_MODELS_PER_SURFACE]:
        if not isinstance(entry, Mapping):
            continue
        model = _sanitize_model(entry)
        if model is not None:
            cleaned.append(model)
    return cleaned


def sanitize_native_models(raw: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Allowlisted values-only rows. Unknown surfaces and extra keys drop."""
    cleaned: dict[str, dict[str, Any]] = {}
    if not isinstance(raw, Mapping):
        return cleaned
    for surface in NATIVE_MODEL_SURFACES:
        row = raw.get(surface)
        if not isinstance(row, Mapping):
            continue
        status = str(row.get("status") or "unknown")
        if status not in NATIVE_MODEL_STATUSES:
            status = "unknown"
        models = _sanitize_models(row.get("models"))
        if status == "ok" and not models:
            # A fresh success with nothing in it is the one shape that would
            # read as "this account can select no models at all".
            status = "unknown"
        cleaned[surface] = {
            "surface": surface,
            "status": status,
            "reason": _clip(row.get("reason")),
            "source": _clip(row.get("source")) or "",
            "observed_at": _clip(row.get("observed_at")) or "",
            "models": models,
        }
    return cleaned


def available_models(reading: Mapping[str, Any] | None) -> tuple[str, ...]:
    """Model tokens a surface published, whether the reading is fresh or stale.

    A stale reading still names real models. Dropping them because the last
    probe failed is what would turn a momentary outage into a surface that
    appears to offer nothing.
    """
    models = (reading or {}).get("models")
    if not isinstance(models, Sequence) or isinstance(models, (str, bytes)):
        return ()
    return tuple(
        str(entry["model"])
        for entry in models
        if isinstance(entry, Mapping) and entry.get("model")
    )


__all__ = [
    "MAX_MODELS_PER_SURFACE",
    "NATIVE_MODEL_STATUSES",
    "NATIVE_MODEL_SURFACES",
    "NO_ADAPTER_REASON",
    "TRUNCATED_REASON",
    "available_models",
    "empty_reading",
    "models_reading",
    "native_model",
    "sanitize_native_models",
    "stale_reading",
]
