"""Who may consume a registered machine's capacity, and what it offers.

A machine is a capacity pool. Many people and many machines share one universe,
so a machine row carries an access document saying which same-universe actors
may spend its capacity and what shape that capacity has. The document is pure
data with a pure decision function here; resolving an actor's roles and admin
standing is the control plane's job, and it hands the resolved facts in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence


USE_OWNER_ONLY = "owner_only"
USE_ACTORS = "actors"
USE_PROJECT_ROLE = "project_role"
USE_UNIVERSE = "universe"
USE_MODES = (USE_OWNER_ONLY, USE_ACTORS, USE_PROJECT_ROLE, USE_UNIVERSE)

USE_SETTING = "access.use.mode"
DEFAULT_ACCESS: dict[str, Any] = {
    "use": {"mode": USE_OWNER_ONLY, "actor_ids": [], "project_id": None, "role": ""},
    "offers": {
        "executor_surfaces": [],
        "models": [],
        "qa_host": False,
        "deploys": False,
    },
}


@dataclass(frozen=True)
class AccessDecision:
    """Whether an actor may use a machine, and which setting decided it."""

    allowed: bool
    setting: str
    reason: str


def _int_list(value: Any) -> list[int]:
    if not isinstance(value, (list, tuple)):
        return []
    out: list[int] = []
    for item in value:
        try:
            parsed = int(item)
        except (TypeError, ValueError):
            continue
        if parsed > 0 and parsed not in out:
            out.append(parsed)
    return sorted(out)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in out:
            out.append(text)
    return sorted(out)


def normalize_access(document: Any) -> dict[str, Any]:
    """Return the document with every declared key present and typed."""
    raw = document if isinstance(document, Mapping) else {}
    use = raw.get("use") if isinstance(raw.get("use"), Mapping) else {}
    offers = raw.get("offers") if isinstance(raw.get("offers"), Mapping) else {}
    mode = str(use.get("mode") or USE_OWNER_ONLY).strip()
    project_id: int | None
    try:
        project_id = int(use["project_id"])  # type: ignore[index]
    except (KeyError, TypeError, ValueError):
        project_id = None
    return {
        "use": {
            "mode": mode if mode in USE_MODES else mode,
            "actor_ids": _int_list(use.get("actor_ids")),
            "project_id": project_id if project_id and project_id > 0 else None,
            "role": str(use.get("role") or "").strip(),
        },
        "offers": {
            "executor_surfaces": _string_list(offers.get("executor_surfaces")),
            "models": _string_list(offers.get("models")),
            "qa_host": bool(offers.get("qa_host", False)),
            "deploys": bool(offers.get("deploys", False)),
        },
    }


def validate_access(document: Any) -> tuple[str, ...]:
    """Return one message per malformed field, empty when the document holds."""
    normalized = normalize_access(document)
    use = normalized["use"]
    issues: list[str] = []
    mode = use["mode"]
    if mode not in USE_MODES:
        issues.append(
            f"{USE_SETTING} must be one of {', '.join(USE_MODES)}; got {mode!r}"
        )
    if mode == USE_ACTORS and not use["actor_ids"]:
        issues.append(
            f"{USE_SETTING}={USE_ACTORS} needs a non-empty access.use.actor_ids list"
        )
    if mode == USE_PROJECT_ROLE and not (use["project_id"] and use["role"]):
        issues.append(
            f"{USE_SETTING}={USE_PROJECT_ROLE} needs access.use.project_id and "
            "access.use.role"
        )
    return tuple(issues)


def access_permits(
    document: Any,
    *,
    actor_id: int,
    owner_actor_id: int,
    is_admin: bool = False,
    project_role_names: Iterable[str] = (),
) -> AccessDecision:
    """Decide whether ``actor_id`` may spend this machine's capacity.

    The owner and an administrator always may — an operator locked out of a
    machine they own has no recovery that does not involve the database.
    """
    normalized = normalize_access(document)
    use = normalized["use"]
    mode = use["mode"]
    if int(actor_id) == int(owner_actor_id):
        return AccessDecision(True, USE_SETTING, "actor owns the machine")
    if is_admin:
        return AccessDecision(True, USE_SETTING, "actor administers this universe")
    if mode == USE_UNIVERSE:
        return AccessDecision(
            True, USE_SETTING, f"{USE_SETTING}={USE_UNIVERSE} admits every member"
        )
    if mode == USE_ACTORS:
        if int(actor_id) in use["actor_ids"]:
            return AccessDecision(
                True, USE_SETTING, f"{USE_SETTING}={USE_ACTORS} names this actor"
            )
        return AccessDecision(
            False,
            USE_SETTING,
            f"{USE_SETTING}={USE_ACTORS} and this actor is not on the list",
        )
    if mode == USE_PROJECT_ROLE:
        wanted = use["role"]
        held = {str(name).strip() for name in project_role_names}
        if wanted and wanted in held:
            return AccessDecision(
                True,
                USE_SETTING,
                f"{USE_SETTING}={USE_PROJECT_ROLE} and this actor holds {wanted}",
            )
        return AccessDecision(
            False,
            USE_SETTING,
            f"{USE_SETTING}={USE_PROJECT_ROLE} requires project role {wanted!r}, "
            "which this actor does not hold",
        )
    if mode == USE_OWNER_ONLY:
        return AccessDecision(
            False,
            USE_SETTING,
            f"{USE_SETTING}={USE_OWNER_ONLY} and this actor is not the owner",
        )
    return AccessDecision(
        False,
        USE_SETTING,
        f"{USE_SETTING}={mode!r} is not a recognized mode; the machine admits "
        "nobody until its owner or an administrator repairs the setting",
    )


def offers_surface(document: Any, surface: str) -> bool:
    """An empty offer list narrows nothing; a populated one is exhaustive."""
    offered: Sequence[str] = normalize_access(document)["offers"]["executor_surfaces"]
    return not offered or str(surface).strip() in offered


def offers_model(document: Any, model: str) -> bool:
    offered: Sequence[str] = normalize_access(document)["offers"]["models"]
    return not offered or str(model).strip() in offered


__all__ = [
    "AccessDecision",
    "DEFAULT_ACCESS",
    "USE_ACTORS",
    "USE_MODES",
    "USE_OWNER_ONLY",
    "USE_PROJECT_ROLE",
    "USE_SETTING",
    "USE_UNIVERSE",
    "access_permits",
    "normalize_access",
    "offers_model",
    "offers_surface",
    "validate_access",
]
