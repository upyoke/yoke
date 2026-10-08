"""The machine state a machine-run QA case starts from, declared per case.

A case that drives a Test Machine runs on whatever that machine holds when it
begins, so the state is part of the case and never left to the runner. Each
machine-run case declares exactly one of:

- ``baseline``: its ``host_baselines`` name the registered baselines the
  runner resets to before it starts (one materialized row per baseline);
- ``inherit``: it starts on the machine exactly as the immediately preceding
  case of the same plan run, at the same baseline position, left it;
- ``as_is``: it runs on the machine as found, with a stated reason.

A ``baseline`` or ``as_is`` case opens a chain; the ``inherit`` cases right
after it extend that chain. The runner resets before a chain and restores the
chain's starting state after its last case.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from yoke_contracts.machine_qa_host_control import HOST_BASELINES

BASELINE = "baseline"
INHERIT = "inherit"
AS_IS = "as_is"
STARTING_STATES = (BASELINE, INHERIT, AS_IS)
MISSION_RUNNER_ID = "agent_mission"
MACHINE_RUNNER_IDS = frozenset({"host_control", MISSION_RUNNER_ID})
STARTING_STATE_RECOVERY = (
    "declare it on the case: `host_baselines` naming a registered baseline "
    f'({", ".join(HOST_BASELINES)}), `starting_state: "inherit"` to start '
    "on the machine as the preceding case left it, or `starting_state: "
    '"as_is"` with a `starting_state_reason`; edit the plan with `yoke qa '
    "plan edit PLAN_SLUG --project P` or replace its cases with `yoke qa "
    "plan-cases replace --project P --plan-id N --stdin`"
)


class StartingStateError(ValueError):
    """A machine-run case's starting state is missing or impossible."""


def is_machine_runner(runner_id: Any) -> bool:
    return str(runner_id or "") in MACHINE_RUNNER_IDS


def normalize_starting_state(
    *,
    case_key: str,
    runner_id: Any,
    host_baselines: Sequence[str],
    starting_state: Any,
    starting_state_reason: Any,
) -> tuple[str | None, str | None]:
    """Return one case's stored ``(starting_state, starting_state_reason)``."""
    declared = None if starting_state in (None, "") else str(starting_state)
    reason = str(starting_state_reason or "").strip() or None
    subject = f"case {case_key!r}"
    if not is_machine_runner(runner_id):
        if declared is not None or reason is not None or host_baselines:
            raise StartingStateError(
                f"{subject} declares a starting state, but only machine-run "
                "cases (host_control and agent_mission methods) start on a "
                "Test Machine; remove host_baselines, starting_state and "
                "starting_state_reason"
            )
        return None, None
    if declared is not None and declared not in STARTING_STATES:
        raise StartingStateError(
            f"{subject} starting_state {declared!r} is not one of "
            f"{', '.join(STARTING_STATES)}"
        )
    unknown = [name for name in host_baselines if name not in HOST_BASELINES]
    if unknown:
        raise StartingStateError(
            f"{subject} names unregistered host baselines {', '.join(unknown)}; "
            f"available baselines: {', '.join(HOST_BASELINES)}"
        )
    if host_baselines:
        if declared not in (None, BASELINE) or reason is not None:
            raise StartingStateError(
                f"{subject} names host_baselines and starting_state "
                f"{declared!r}; a case starts from named baselines or "
                "declares inherit / as_is, never both"
            )
        return BASELINE, None
    if declared is None:
        raise StartingStateError(
            f"{subject} declares no starting state; {STARTING_STATE_RECOVERY}"
        )
    if declared == BASELINE:
        raise StartingStateError(
            f"{subject} declares starting_state 'baseline' with no "
            f"host_baselines; name one of {', '.join(HOST_BASELINES)}"
        )
    if declared == AS_IS and reason is None:
        raise StartingStateError(
            f"{subject} runs as-is without a starting_state_reason; state why "
            "the machine's current contents are the intended starting point"
        )
    if declared == INHERIT and reason is not None:
        raise StartingStateError(
            f"{subject} inherits its starting state, which takes no "
            "starting_state_reason"
        )
    return declared, reason


def chain_baselines(
    cases: Sequence[Mapping[str, Any]],
) -> dict[str, list[str | None]]:
    """Validate an ordered plan and return each case's materialized fan-out.

    ``cases`` are in plan position order and carry ``case_key``,
    ``runner_id``, ``host_baselines``, ``starting_state`` and
    ``starting_state_reason``. A ``baseline`` case fans out across its named
    baselines, an ``as_is`` case materializes once, and an ``inherit`` case
    follows its predecessor's fan-out so each of its rows continues the row
    at the same baseline position.
    """
    fan_out: dict[str, list[str | None]] = {}
    previous: Mapping[str, Any] | None = None
    for case in cases:
        key = str(case["case_key"])
        baselines = list(case.get("host_baselines") or [])
        state, _ = normalize_starting_state(
            case_key=key,
            runner_id=case.get("runner_id"),
            host_baselines=baselines,
            starting_state=case.get("starting_state"),
            starting_state_reason=case.get("starting_state_reason"),
        )
        if state == INHERIT:
            if previous is None:
                raise StartingStateError(
                    f"case {key!r} inherits its starting state, but it is the "
                    "plan's first case and nothing runs before it; declare "
                    "host_baselines or starting_state 'as_is' instead"
                )
            if MISSION_RUNNER_ID in (case.get("runner_id"), previous.get("runner_id")):
                raise StartingStateError(
                    f"case {key!r} inherits from case "
                    f"{str(previous['case_key'])!r}, but an exploratory "
                    "mission is walked after the plan's other cases, so no "
                    "case runs directly before or after it on the machine; "
                    "declare host_baselines or starting_state 'as_is' instead"
                )
            if not is_machine_runner(previous.get("runner_id")):
                raise StartingStateError(
                    f"case {key!r} inherits from case "
                    f"{str(previous['case_key'])!r}, which does not run on a "
                    "Test Machine; an inheriting case must directly follow a "
                    "machine-run case"
                )
            fan_out[key] = list(fan_out[str(previous["case_key"])])
        elif state == BASELINE:
            fan_out[key] = baselines
        else:
            fan_out[key] = [None]
        previous = case
    return fan_out


def stored_fan_out(cases: Sequence[Mapping[str, Any]]) -> list[list[str | None]]:
    """Each stored case's materialized baselines, read without validating.

    The read-side twin of :func:`chain_baselines` for plans as they are
    stored: a case with ``host_baselines`` fans out across them, an
    ``inherit`` case follows its predecessor, and any other case is one row
    with no baseline. ``host_baselines`` is the decoded list.
    """
    fan_out: list[list[str | None]] = []
    previous: list[str | None] = [None]
    for case in cases:
        if case.get("starting_state") != INHERIT:
            previous = list(case.get("host_baselines") or []) or [None]
        fan_out.append(previous)
    return fan_out


def require_selected_chains(
    plan_cases: Sequence[Mapping[str, Any]],
    selected_keys: Sequence[str],
) -> None:
    """Refuse a case selection that runs an inheriting case off its chain.

    An ``inherit`` case is only meaningful directly after the case it
    inherits from, so a selection of a plan's cases must keep each selected
    inheriting case immediately behind its plan predecessor.
    """
    order = [str(case["case_key"]) for case in plan_cases]
    states = {str(case["case_key"]): case.get("starting_state") for case in plan_cases}
    for index, key in enumerate(selected_keys):
        if states.get(key) != INHERIT:
            continue
        predecessor = order[order.index(key) - 1]
        if index == 0 or selected_keys[index - 1] != predecessor:
            raise StartingStateError(
                f"case {key!r} inherits the machine case {predecessor!r} "
                "leaves behind, so it can only be selected directly after "
                f"{predecessor!r}; select {predecessor!r} before it"
            )


def _field(case: Any, name: str) -> Any:
    return case.get(name) if isinstance(case, Mapping) else getattr(case, name)


def reset_baselines(case: Any, *, continues: bool = False) -> list[str]:
    """The baseline a materialized case resets to before it runs, if any.

    Only a case that starts a chain from a named baseline resets; an
    inheriting case keeps its predecessor's machine, an ``as_is`` case runs
    on the machine as found, and a continued mission walk keeps its host.
    """
    baseline = _field(case, "host_baseline")
    if continues or _field(case, "starting_state") != BASELINE or not baseline:
        return []
    return [str(baseline)]


def require_materialized_starting_state(case: Any) -> None:
    """Refuse a materialized machine case that cannot say where it starts."""
    requirement_id = _field(case, "requirement_id")
    state = _field(case, "starting_state")
    if state is None:
        raise StartingStateError(
            f"Machine QA requirement {requirement_id} declares no starting "
            f"state; {STARTING_STATE_RECOVERY}, then refresh the materialized "
            "case (yoke qa plan rematerialize) or add it again with "
            "--host-baseline or --starting-state as_is"
        )
    baseline = _field(case, "host_baseline")
    if (state == BASELINE and not baseline) or (state == AS_IS and baseline):
        raise StartingStateError(
            f"Machine QA requirement {requirement_id} starting state "
            f"{state!r} disagrees with its host baseline {baseline!r}"
        )


__all__ = [
    "AS_IS",
    "BASELINE",
    "INHERIT",
    "MACHINE_RUNNER_IDS",
    "STARTING_STATES",
    "STARTING_STATE_RECOVERY",
    "StartingStateError",
    "chain_baselines",
    "is_machine_runner",
    "normalize_starting_state",
    "require_materialized_starting_state",
    "require_selected_chains",
    "reset_baselines",
    "stored_fan_out",
]
