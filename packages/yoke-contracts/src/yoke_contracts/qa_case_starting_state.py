"""Declare the baseline for each Test Machine QA chain.

A chain starts by resetting to a registered baseline. Each explicit
``inherit`` case continues the immediately preceding case's machine at
the same baseline position in the same plan run.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from yoke_contracts.hook_runner.shell_parse import parse_shell
from yoke_contracts.machine_qa_host_control import HOST_BASELINES

BASELINE = "baseline"
INHERIT = "inherit"
STARTING_STATES = (BASELINE, INHERIT)
MISSION_RUNNER_ID = "agent_mission"
STARTING_STATE_RECOVERY = (
    "declare it on the case: `host_baselines` naming a registered baseline "
    f'({", ".join(HOST_BASELINES)}), `starting_state: "inherit"` to start '
    "on the machine as the preceding case left it; edit the plan with `yoke qa "
    "plan edit PLAN_SLUG --project P` or replace its cases with `yoke qa "
    "plan-cases replace --project P --plan-id N --stdin`"
)


class StartingStateError(ValueError):
    """A machine-run case's starting state is missing or impossible."""


def needs_test_machine(case: Mapping[str, Any]) -> bool:
    """Whether the case declares work on a Test Machine, independent of run pins."""
    runner = case.get("runner_id")
    if runner == "host_control":
        return True
    if runner != MISSION_RUNNER_ID:
        return False
    config = _method_config(case)
    required = []
    for field in ("capability_requirements", "required_capability_kinds"):
        kinds = case.get(field) or []
        required.extend(json.loads(kinds) if isinstance(kinds, str) else kinds)
    return bool(
        any(
            config.get(key)
            for key in ("test_machine", "test_machines", "os", "platform", "capability_tags")
        )
        or any(str(kind).startswith("test-machine:") for kind in required)
        or case.get("host_baselines")
        or case.get("host_baseline")
    )


def is_host_command(case: Mapping[str, Any]) -> bool:
    """Whether the case is a Command that names the Test Machine it reaches."""
    if case.get("runner_id") != "worktree_run":
        return False
    config = _method_config(case)
    return bool(config.get("test_machine"))


def declares_starting_state(case: Mapping[str, Any]) -> bool:
    """Whether the case may carry a starting state on a Test Machine."""
    return needs_test_machine(case) or is_host_command(case)


def normalize_starting_state(
    *,
    case_key: str,
    runner_id: Any,
    host_baselines: Sequence[str],
    starting_state: Any,
    starting_state_reason: Any,
    method_config: Any = None,
    capability_requirements: Any = None,
) -> tuple[str | None, str | None]:
    """Normalize machine state; ignore stale declarations on non-machine cases."""
    declared = None if starting_state in (None, "") else str(starting_state)
    reason = str(starting_state_reason or "").strip() or None
    subject = f"case {case_key!r}"
    shape = dict(
        runner_id=runner_id,
        host_baselines=host_baselines,
        method_config=method_config,
        capability_requirements=capability_requirements,
    )
    if not declares_starting_state(shape):
        return None, None
    if declared is not None and declared not in STARTING_STATES:
        raise StartingStateError(
            f"{subject} starting_state {declared!r} is not one of "
            f"{', '.join(STARTING_STATES)}; {STARTING_STATE_RECOVERY}"
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
                "declares inherit, never both"
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
    if declared == INHERIT and reason is not None:
        raise StartingStateError(
            f"{subject} inherits its starting state, which takes no "
            "starting_state_reason"
        )
    return declared, reason


def _method_config(case: Mapping[str, Any]) -> Mapping[str, Any]:
    config = case.get("method_config") or {}
    return json.loads(config) if isinstance(config, str) else config


_YOKE_PROGRAMS = {"yoke", "yoke.exe", "{yoke_bin}", "$YOKE_BIN", "${YOKE_BIN}"}
_YOKE_LIFECYCLE = re.compile(r"(^|[-_ ])(?:uninstall|upgrade)(?=$|[-_ ])")


def _runs_yoke(command: str) -> bool:
    for segment in parse_shell(command).segments:
        if segment.program not in _YOKE_PROGRAMS:
            continue
        argv = segment.argv[1:]
        if "test-machine" in argv:
            # These commands reach the host from the controller.
            if "--" in argv:
                remote = argv[argv.index("--") + 1 :]
                if remote and _runs_yoke(" ".join(remote)):
                    return True
            continue
        return True
    return False


def requires_host_yoke(case: Mapping[str, Any]) -> bool:
    """Whether a machine case needs an installed Yoke on its starting host."""
    config = _method_config(case)
    if config.get("browser_identities") or _YOKE_LIFECYCLE.search(
        str(case.get("case_key") or "").lower()
    ):
        return True
    commands = [config.get("command"), case.get("entry_surface")]
    for step in (*(config.get("steps") or []), *(config.get("assertions") or [])):
        if isinstance(step, str):
            commands.append(step)
        elif isinstance(step, Mapping):
            commands.extend((step.get("command"), step.get("send")))
            argv = step.get("argv") or []
            if argv and str(argv[0]).rsplit("/", 1)[-1] in _YOKE_PROGRAMS:
                return True
    return any(isinstance(command, str) and _runs_yoke(command) for command in commands)


def _require_yoke_baseline(case: Mapping[str, Any], baseline: str | None) -> None:
    if baseline != "fresh-host":
        return
    config = _method_config(case)
    variants = config.get("baseline_configs") or {}
    effective_case = {**case, "method_config": variants.get(baseline, config)}
    if requires_host_yoke(effective_case):
        raise StartingStateError(
            f"starting_state_lacks_yoke: case {case['case_key']!r} runs Yoke "
            "on the Test Machine, but starts from fresh-host; declare "
            "shell-preconfigured on the chain head or start a separate "
            "shell-preconfigured chain"
        )


def chain_baselines(
    cases: Sequence[Mapping[str, Any]],
) -> dict[str, list[str | None]]:
    """Validate an ordered plan and return each case's materialized fan-out.

    ``cases`` are in plan position order and carry ``case_key``,
    ``runner_id``, ``host_baselines``, ``starting_state`` and
    ``starting_state_reason`` and ``method_config``. A baseline case fans out
    across named baselines. An inheriting case follows its predecessor's fan-out.
    """
    fan_out: dict[str, list[str | None]] = {}
    previous: Mapping[str, Any] | None = None
    for case in cases:
        key = str(case["case_key"])
        baselines = list(case.get("host_baselines") or [])
        state, _ = normalize_starting_state(
            case_key=key,
            runner_id=case.get("runner_id"),
            method_config=case.get("method_config"),
            capability_requirements=case.get("capability_requirements")
            or case.get("required_capability_kinds"),
            host_baselines=baselines,
            starting_state=case.get("starting_state"),
            starting_state_reason=case.get("starting_state_reason"),
        )
        if state == INHERIT:
            if previous is None:
                raise StartingStateError(
                    f"case {key!r} inherits its starting state, but it is the "
                    "plan's first case and nothing runs before it; declare "
                    "host_baselines instead"
                )
            if previous.get("runner_id") == MISSION_RUNNER_ID:
                raise StartingStateError(
                    f"case {key!r} inherits from case "
                    f"{str(previous['case_key'])!r}, but an exploratory "
                    "mission is walked after the plan's captures, so no "
                    "case may inherit after it on the machine; "
                    "declare host_baselines instead"
                )
            if not declares_starting_state(previous):
                raise StartingStateError(
                    f"case {key!r} inherits from case "
                    f"{str(previous['case_key'])!r}, which does not run on a "
                    "Test Machine; an inheriting case must directly follow a "
                    "machine-run case"
                )

            if _method_config(case).get("test_machine") != _method_config(previous).get(
                "test_machine"
            ):
                raise StartingStateError(
                    f"inherited_driver_mismatch: case {key!r} inherits from "
                    f"case {str(previous['case_key'])!r}, but their driving "
                    "machines differ; use the predecessor's "
                    "method_config.test_machine or declare host_baselines instead"
                )
            fan_out[key] = list(fan_out[str(previous["case_key"])])
        elif state == BASELINE:
            fan_out[key] = baselines
        else:
            fan_out[key] = [None]
        for baseline in fan_out[key]:
            _require_yoke_baseline(case, baseline)
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

    A chain head always resets. Inheriting cases and continued mission
    walks retain the state of their own execution.
    """
    baseline = _field(case, "host_baseline")
    if continues or _field(case, "starting_state") == INHERIT or not baseline:
        return []
    return [str(baseline)]


def require_materialized_starting_state(case: Any) -> None:
    """Refuse a materialized machine case that cannot say where it starts."""
    requirement_id = _field(case, "requirement_id")
    state = _field(case, "starting_state")
    if state not in STARTING_STATES:
        raise StartingStateError(
            f"Machine QA requirement {requirement_id} declares no valid starting "
            f"state ({state!r}); {STARTING_STATE_RECOVERY}, then refresh the "
            "materialized case with `yoke qa plan rematerialize`"
        )
    baseline = _field(case, "host_baseline")
    if baseline not in HOST_BASELINES:
        raise StartingStateError(
            f"Machine QA requirement {requirement_id} starting state "
            f"{state!r} disagrees with its host baseline {baseline!r}; "
            f"{STARTING_STATE_RECOVERY}"
        )


__all__ = [
    "BASELINE",
    "INHERIT",
    "STARTING_STATES",
    "STARTING_STATE_RECOVERY",
    "StartingStateError",
    "chain_baselines",
    "declares_starting_state",
    "is_host_command",
    "needs_test_machine",
    "normalize_starting_state",
    "require_materialized_starting_state",
    "require_selected_chains",
    "requires_host_yoke",
    "reset_baselines",
    "stored_fan_out",
]
