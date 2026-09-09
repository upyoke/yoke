"""Selector rules that route a registering session to a project lane.

``executor_default_lanes`` answers "which lane does this harness get?" and
nothing more, so a project running two model tiers on one harness has no
way to separate them. ``lane_rules`` is the additive selector list that
does: each entry names a lane and matches on harness, on model, or on
both.

Precedence is by how specific the selector is, never by where the entry
sits in the list — an operator reordering the document must not change
where sessions land:

1. an explicit lane the caller supplied (resolved before this module);
2. harness and model together;
3. model alone;
4. harness alone;
5. the ``executor_default_lanes`` harness default.

Within a tier, an exact model identifier outranks a trailing-star prefix,
and a longer prefix outranks a shorter one. Two entries cannot tie:
equal-length prefixes that both match are the same prefix, and that is a
duplicate selector this module refuses at parse time.

A session whose model is unknown matches only the harness tiers. That is
the explicit answer rather than an accident — a model selector cannot be
evaluated against a model nobody attested, and quietly treating the
absence as a non-match at a *lower* tier would let a session land on a
lane the operator scoped to a model it may well be running.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence

from yoke_contracts.executor_labels import CANONICAL_HARNESS_IDS, canonical_harness_id
from yoke_contracts.session_model_facts import CLAUDE_CONTEXT_TIER_SUFFIX


_WILDCARD = "*"


class LaneRuleError(ValueError):
    """Raised when a ``lane_rules`` entry cannot be accepted as written."""

    def __init__(self, message: str, *, field: str) -> None:
        super().__init__(message)
        self.field = field


@dataclass(frozen=True)
class LaneRule:
    """One accepted selector: a lane plus the facts it matches on."""

    lane: str
    harness: Optional[str] = None
    model: Optional[str] = None

    @property
    def model_is_prefix(self) -> bool:
        return bool(self.model) and str(self.model).endswith(_WILDCARD)

    @property
    def selector(self) -> tuple[Optional[str], Optional[str]]:
        """The identity two entries may not share."""
        return (self.harness, self.model)

    def as_payload(self) -> dict[str, Optional[str]]:
        """Shape one rule for a registered read's result payload."""
        return {"lane": self.lane, "harness": self.harness, "model": self.model}


def _require_mapping(entry: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(entry, Mapping):
        raise LaneRuleError(
            f"{field} must be an object with a lane and at least one of "
            f"harness or model; got {type(entry).__name__}.",
            field=field,
        )
    return entry


def _parse_harness(raw: Any, *, field: str) -> Optional[str]:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if not isinstance(raw, str):
        raise LaneRuleError(
            f"{field}.harness must be a string naming a supported harness; "
            f"got {type(raw).__name__}.",
            field=f"{field}.harness",
        )
    try:
        return canonical_harness_id(raw)
    except ValueError as exc:
        raise LaneRuleError(
            f"{field}.harness names an unsupported harness ({raw!r}): {exc}. "
            f"Supported harnesses are {', '.join(CANONICAL_HARNESS_IDS)}.",
            field=f"{field}.harness",
        ) from exc


def _parse_model(raw: Any, *, field: str) -> Optional[str]:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if not isinstance(raw, str):
        raise LaneRuleError(
            f"{field}.model must be a string naming a model or a trailing-star "
            f"prefix such as 'claude-opus-*'; got {type(raw).__name__}.",
            field=f"{field}.model",
        )
    model = raw.strip()
    star_count = model.count(_WILDCARD)
    if star_count == 0:
        return model
    if star_count > 1 or not model.endswith(_WILDCARD):
        raise LaneRuleError(
            f"{field}.model may use one trailing '*' and nothing else; "
            f"{model!r} is not a supported pattern. Write an exact model "
            "identifier, or a family prefix such as 'claude-opus-*'.",
            field=f"{field}.model",
        )
    if len(model) == 1:
        raise LaneRuleError(
            f"{field}.model must not be a bare '*' — a rule matching every "
            "model is what executor_default_lanes already expresses.",
            field=f"{field}.model",
        )
    return model


def _parse_lane(
    raw: Any, *, field: str, declared_lanes: Optional[Sequence[str]]
) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise LaneRuleError(
            f"{field}.lane must name a declared lane.",
            field=f"{field}.lane",
        )
    lane = raw.strip()
    if declared_lanes is not None and lane not in declared_lanes:
        raise LaneRuleError(
            f"{field}.lane names {lane!r}, which this project does not "
            f"declare. Declared lanes are "
            f"{', '.join(sorted(declared_lanes)) or '(none)'}; declare the "
            "lane in lane_metadata or lane_paths first.",
            field=f"{field}.lane",
        )
    return lane


def parse_lane_rules(
    raw: Any,
    *,
    declared_lanes: Optional[Iterable[str]],
    field: str = "lane_rules",
) -> tuple[LaneRule, ...]:
    """Return the accepted rules, refusing anything that cannot route.

    ``declared_lanes`` of ``None`` skips the lane-declaration check for
    the read path, where a lane naming is the settings validator's job
    and re-litigating it would only turn a stored document into a
    registration failure.
    """
    if raw is None:
        return ()
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise LaneRuleError(
            f"{field} must be a list of selector objects; got "
            f"{type(raw).__name__}.",
            field=field,
        )
    lanes = None if declared_lanes is None else tuple(declared_lanes)
    rules: list[LaneRule] = []
    seen: dict[tuple[Optional[str], Optional[str]], str] = {}
    for index, entry in enumerate(raw):
        entry_field = f"{field}[{index}]"
        mapping = _require_mapping(entry, field=entry_field)
        unknown = sorted(set(mapping) - {"lane", "harness", "model"})
        if unknown:
            raise LaneRuleError(
                f"{entry_field} carries unsupported key(s) "
                f"{', '.join(unknown)}; a rule has only lane, harness, and "
                "model.",
                field=entry_field,
            )
        harness = _parse_harness(mapping.get("harness"), field=entry_field)
        model = _parse_model(mapping.get("model"), field=entry_field)
        if harness is None and model is None:
            raise LaneRuleError(
                f"{entry_field} matches nothing: give it a harness, a model, "
                "or both. A rule that matches every session is what "
                "executor_default_lanes already expresses.",
                field=entry_field,
            )
        rule = LaneRule(
            lane=_parse_lane(
                mapping.get("lane"), field=entry_field, declared_lanes=lanes
            ),
            harness=harness,
            model=model,
        )
        previous = seen.get(rule.selector)
        if previous is not None:
            raise LaneRuleError(
                f"{entry_field} repeats a selector already routed to "
                f"{previous!r} (harness={harness!r}, model={model!r}). Two "
                "entries cannot claim the same selector; keep one.",
                field=entry_field,
            )
        seen[rule.selector] = rule.lane
        rules.append(rule)
    return tuple(rules)


def parse_lane_rules_for_routing(raw: Any) -> tuple[LaneRule, ...]:
    """Parse stored rules for the routing path, dropping unusable entries.

    Registration and session offer run on every session, so a document
    that predates a contract tightening must degrade to the harness
    default rather than refuse every session in the project. The write
    boundary is where a bad rule is refused and named;
    :func:`parse_lane_rules` is that boundary.
    """
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return ()
    usable: list[Any] = []
    for entry in raw:
        try:
            parse_lane_rules([*usable, entry], declared_lanes=None)
        except LaneRuleError:
            continue
        usable.append(entry)
    return parse_lane_rules(usable, declared_lanes=None)


def _model_matches(rule: LaneRule, model: Optional[str]) -> bool:
    if rule.model is None:
        return True
    if not model:
        return False
    if rule.model_is_prefix:
        return model.startswith(rule.model[:-1])
    return model == rule.model


def _harness_matches(rule: LaneRule, harness: Optional[str]) -> bool:
    if rule.harness is None:
        return True
    return harness is not None and harness == rule.harness


def _specificity(rule: LaneRule) -> tuple[int, int]:
    """Rank a matching rule: tier first, then how narrow its model is."""
    if rule.harness is not None and rule.model is not None:
        tier = 3
    elif rule.model is not None:
        tier = 2
    else:
        tier = 1
    if rule.model is None:
        narrowness = 0
    elif rule.model_is_prefix:
        narrowness = len(rule.model) - 1
    else:
        # An exact identifier is narrower than any prefix, including one as
        # long as the identifier itself.
        narrowness = len(rule.model) + 1
    return (tier, narrowness)


def canonical_harness_or_none(executor: Optional[str]) -> Optional[str]:
    """Return the harness family for ``executor``, or ``None`` when unknown.

    Registration stores a canonical id, but the value reaching routing can
    also be a surface alias (``claude-cli``) or, on an unrecognised
    executor, something this vocabulary cannot place. Rules match on the
    family, and an unplaceable executor simply matches no harness selector.
    """
    if not executor:
        return None
    try:
        return canonical_harness_id(executor)
    except ValueError:
        return None


def routing_model_of(
    served_model: Optional[str], requested_model: Optional[str]
) -> Optional[str]:
    """Return the model identifier a rule selector should match against.

    A provider-attested model is the truth and wins outright. Most
    sessions have none at registration — the attestation is read back
    from the harness artifact after the fact, while the lane is stamped
    the moment the row is written — so the ask is the fallback, with its
    context-tier selector removed because that suffix describes a
    context window rather than a different model. When neither exists
    the answer is ``None``, and model selectors simply do not apply.
    """
    if served_model and served_model.strip():
        return served_model.strip()
    if not requested_model or not requested_model.strip():
        return None
    asked = requested_model.strip()
    if asked.lower().endswith(CLAUDE_CONTEXT_TIER_SUFFIX):
        asked = asked[: -len(CLAUDE_CONTEXT_TIER_SUFFIX)]
    return asked or None


def resolve_rule_lane(
    rules: Sequence[LaneRule],
    *,
    executor: Optional[str],
    model: Optional[str],
) -> Optional[str]:
    """Return the lane the most specific matching rule names, if any."""
    harness = canonical_harness_or_none(executor)
    best: Optional[LaneRule] = None
    best_rank: tuple[int, int] = (0, 0)
    for rule in rules:
        if not _harness_matches(rule, harness) or not _model_matches(rule, model):
            continue
        rank = _specificity(rule)
        if best is None or rank > best_rank:
            best, best_rank = rule, rank
    return None if best is None else best.lane


__all__ = [
    "LaneRule",
    "LaneRuleError",
    "canonical_harness_or_none",
    "parse_lane_rules",
    "parse_lane_rules_for_routing",
    "resolve_rule_lane",
    "routing_model_of",
]
