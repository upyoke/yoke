"""Normalize carried model facts before storing session identity."""

from __future__ import annotations

from yoke_contracts.session_model_facts import SessionModelFacts


def reclassify_unservable_model(facts: SessionModelFacts) -> SessionModelFacts:
    """Move a wire ``model`` no provider could have served off that slot.

    A placeholder such as ``unknown`` is the absence of an answer and is
    dropped. A context tier selector such as ``claude-opus-5[1m]`` is an
    ask — no provider response returns one — and a client older than this
    contract ships its requested model under the plain key, so during the
    rollout window that is exactly what arrives. It moves to the request
    slot rather than being discarded, because that is what it always was.
    """
    from dataclasses import replace

    from yoke_contracts.session_model_facts import CLAUDE_CONTEXT_TIER_SUFFIX
    from yoke_contracts.session_model_facts import is_placeholder_model

    model = facts.model
    if model is None:
        return facts
    if is_placeholder_model(model):
        return replace(facts, model=None)
    if not model.strip().lower().endswith(CLAUDE_CONTEXT_TIER_SUFFIX):
        return facts
    if facts.requested_model:
        return replace(facts, model=None)
    return replace(facts, model=None, requested_model=model)
