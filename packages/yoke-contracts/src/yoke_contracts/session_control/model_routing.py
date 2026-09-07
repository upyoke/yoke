"""The rule steering applies when it picks a model for a new launch.

Three facts feed a launch model choice, and each is owned somewhere else:
what a surface can actually run right now (native availability), what is
known about a model (the researched reference), and what the operator
prefers. This module owns only the rule that combines them.

Two tiers carry the whole policy. Demanding, ambiguous, or high-consequence
work asks for the operator's tier-1 model; bounded work whose quality bar a
cheaper model already clears asks for tier-2. Anything the operator ranks
below tier-2 is excluded rather than ranked, because a model nobody would
choose does not need a score.

Three named kinds of work pair those tiers with a reasoning level, and that
is the whole routing table. Nothing here classifies work into one: the kind
is an input the steering seat supplies from the task it is already reading,
so there is no complexity field, classifier, or scoring pass. Nothing here
ranks models by name or version either -- a newer number is not evidence of a
better model, and the reference that would say so is separate research.

Whether a model's billing pool is empty is read next door, in
``model_billing_pools``; this module only decides what to do about it.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from yoke_contracts.session_control.model_billing_pools import pool_exhaustion

#: Demanding, ambiguous, or high-consequence work.
TIER1 = "tier1"
#: Bounded work whose quality bar a cheaper model already clears.
TIER2 = "tier2"
#: Ranked below tier2 and therefore not offered to any work.
EXCLUDED = "excluded"
ROUTING_TIERS = (TIER1, TIER2)
#: Every rank the researched reference may propose, this rule included.
MODEL_RANKS = (TIER1, TIER2, EXCLUDED)

#: The three kinds of work a launch is placed for, and the tier and reasoning
#: level each asks for. The ceiling is deliberate: the highest level a vendor
#: offers is not a default, because paying for it on work that does not need
#: it buys nothing and spends a shared allowance faster.
WORK_KINDS: Mapping[str, tuple[str, str]] = {
    "simple": (TIER2, "medium"),
    "normal": (TIER1, "high"),
    "difficult": (TIER1, "xhigh"),
}
#: When a model does not publish the level its work kind asks for, this is
#: what it takes instead. One step, never a climb to whatever is highest.
EFFORT_SUBSTITUTES: Mapping[str, str] = {"xhigh": "high"}

#: The operator's routing policy, beside the per-surface launch defaults it
#: refines. Machine-local because it is a policy about work, not a fact about
#: a provider account.
SESSION_MODEL_ROUTING_KEY = "session_model_routing"
_TIER_KEYS = ROUTING_TIERS
_LIST_KEYS = ("excluded", "fallbacks")


def routing_preference(
    payload: Mapping[str, Any] | None, surface: str
) -> dict[str, Any]:
    """Read one surface's routing policy from the machine config payload.

    Blank is a complete answer: with no policy configured the seat falls back
    to the per-surface launch defaults it already had.
    """
    entry: Any = None
    if isinstance(payload, Mapping):
        raw = payload.get(SESSION_MODEL_ROUTING_KEY)
        if isinstance(raw, Mapping):
            entry = raw.get(surface)
    values: dict[str, Any] = {key: None for key in _TIER_KEYS}
    values.update({key: () for key in _LIST_KEYS})
    if not isinstance(entry, Mapping):
        return values
    for key in _TIER_KEYS:
        values[key] = str(entry.get(key) or "").strip() or None
    for key in _LIST_KEYS:
        raw_list = entry.get(key)
        if isinstance(raw_list, Sequence) and not isinstance(raw_list, (str, bytes)):
            values[key] = tuple(
                str(item).strip() for item in raw_list if str(item or "").strip()
            )
    return values


def normalize_session_model_routing(
    payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Normalize the whole routing document, dropping surfaces that say nothing."""
    raw = (
        payload.get(SESSION_MODEL_ROUTING_KEY) if isinstance(payload, Mapping) else None
    )
    if not isinstance(raw, Mapping):
        return {}
    normalized: dict[str, Any] = {}
    for surface in raw:
        entry = routing_preference(payload, str(surface))
        if any(entry[key] for key in _TIER_KEYS) or any(
            entry[key] for key in _LIST_KEYS
        ):
            normalized[str(surface)] = {
                key: value for key, value in entry.items() if value
            }
    return normalized


def preferred_model_for_tier(
    payload: Mapping[str, Any] | None, surface: str, tier: str
) -> str | None:
    """Name the model the operator routes this tier of work to, if any."""
    if tier not in ROUTING_TIERS:
        return None
    return routing_preference(payload, surface)[tier]


def model_excluded(
    payload: Mapping[str, Any] | None, surface: str, model: str | None
) -> bool:
    """Say whether the operator has excluded this model from new launches."""
    value = str(model or "").strip().lower()
    if not value:
        return False
    excluded = routing_preference(payload, surface)["excluded"]
    return any(value == str(item).strip().lower() for item in excluded)


def fallback_justified(
    payload: Mapping[str, Any] | None,
    surface: str,
    model: str | None,
    fallback: str | None,
    windows: Sequence[Mapping[str, Any]],
) -> tuple[bool, str]:
    """Decide whether a named fallback may take over from the preferred model.

    A fallback usually draws on a separately metered allowance, so it is
    reached only on confirmed exhaustion of the preferred model's own pool
    and only when the operator listed it. Both halves refuse loudly: an
    unlisted fallback is a spend the operator never opted into, and an
    unreadable meter is not permission to start spending.
    """
    candidate = str(fallback or "").strip()
    if not candidate:
        return False, "no fallback named"
    preference = routing_preference(payload, surface)
    if not any(
        candidate.lower() == str(item).strip().lower()
        for item in preference["fallbacks"]
    ):
        return False, f"{candidate} is not a configured fallback for {surface}"
    if model_excluded(payload, surface, candidate):
        return False, f"{candidate} is excluded by operator preference"
    reading = pool_exhaustion(surface, model, windows)
    if not reading.exhausted:
        return False, f"{model or 'the preferred model'}: {reading.reason}"
    return True, f"{reading.pool} is exhausted; falling back to {candidate}"


def routed_selection(
    payload: Mapping[str, Any] | None,
    surface: str,
    work_kind: str,
    model_entry: Mapping[str, Any] | None = None,
) -> tuple[str | None, str | None]:
    """Resolve one work kind into the model and effort a new launch asks for.

    The model comes from the operator's per-surface preference for that tier,
    and blank means the surface keeps whatever default it already had. The
    effort is the work kind's level, stepped down when the chosen model does
    not publish it -- asking a model for a level it never offered is a launch
    the vendor rejects.

    This decides a NEW launch. A running session keeps the selection it
    started with, and a resume re-sends that selection rather than this one.
    """
    if work_kind not in WORK_KINDS:
        return None, None
    tier, effort = WORK_KINDS[work_kind]
    model = preferred_model_for_tier(payload, surface, tier)
    if model_excluded(payload, surface, model):
        model = None
    return model, resolved_effort(effort, model_entry)


def resolved_effort(effort: str, model_entry: Mapping[str, Any] | None = None) -> str:
    """Step an unsupported level down to the one the operator named for it.

    With no per-model facts to read, the asked-for level stands: an unknown
    model has not refused anything, and guessing it down would quietly buy
    less than the work kind called for.
    """
    published = supported_reasoning_efforts(model_entry)
    if not published or effort in published:
        return effort
    substitute = EFFORT_SUBSTITUTES.get(effort)
    if substitute and substitute in published:
        return substitute
    return effort


def replacement_for(entry: Mapping[str, Any] | None) -> str | None:
    """Name the model a vendor says supersedes this one, for NEW launches only.

    Adoption follows the vendor's own replacement metadata rather than a
    version number read off the id. A running session keeps the selection it
    started with; replacing a worker's model means launching a new one.
    """
    if not isinstance(entry, Mapping):
        return None
    return str(entry.get("replaced_by") or "").strip() or None


def supported_reasoning_efforts(entry: Mapping[str, Any] | None) -> tuple[str, ...]:
    """List the efforts a specific model published, not the surface's union.

    A surface accepts a set of effort levels; an individual model may accept
    fewer. Asking for one the model does not publish is a launch the vendor
    rejects, so the per-model list is the one to choose from.
    """
    if not isinstance(entry, Mapping):
        return ()
    raw = entry.get("reasoning_efforts")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return ()
    return tuple(str(item).strip() for item in raw if str(item or "").strip())


__all__ = [
    "EFFORT_SUBSTITUTES",
    "EXCLUDED",
    "MODEL_RANKS",
    "ROUTING_TIERS",
    "SESSION_MODEL_ROUTING_KEY",
    "WORK_KINDS",
    "TIER1",
    "TIER2",
    "fallback_justified",
    "model_excluded",
    "normalize_session_model_routing",
    "preferred_model_for_tier",
    "replacement_for",
    "resolved_effort",
    "routed_selection",
    "routing_preference",
    "supported_reasoning_efforts",
]
