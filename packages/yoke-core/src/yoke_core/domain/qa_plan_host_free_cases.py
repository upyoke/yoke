"""Host-free automatic cases a scoped QA plan runs while it waits for a host.

A plan execution walks its roster in order, but a Command or Command (CI) case
needs no Test Machine and belongs to no machine chain. When a machine case
queues the execution in its host's line, the runner first walks every later
host-free automatic case through the ordinary case runner and records each
result at its own ordinal. The server accepts those results ahead of the
cursor; the cursor skips them when the walk reaches them on the host.
Machine cases, chains and agent- or human-judged cases keep their order.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from yoke_core.domain.qa_method_definitions import BUILTIN_QA_METHODS

#: Runners whose cases need no host and whose verdict is the run itself.
HOST_FREE_RUNNERS = frozenset(
    str(method["runner_id"])
    for method in BUILTIN_QA_METHODS
    if method["proof_kind"] == "command" and method["verdict_path"] == "automatic"
)


def is_host_free_case(case: Mapping[str, Any]) -> bool:
    """Whether a roster case may run and record ahead of the plan cursor."""
    return str(case.get("runner_id") or "") in HOST_FREE_RUNNERS


def run_host_free_cases_while_waiting(
    *,
    requirements: list[dict[str, Any]],
    after_ordinal: int,
    done_ordinals: set[int],
    execute_case: Callable[[dict[str, Any]], dict[str, Any]],
    record_result: Callable[[int, dict[str, Any]], None],
    check_in: Callable[[], None],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Run and record every later host-free case not yet recorded.

    Returns the recorded results and a note per case that could not run.
    A failing verdict is recorded like any other result. A case whose runner
    raises is left unrecorded, so the walk runs it in order on resume; a
    refused check-in or recording stops this pass. Neither ends the host
    wait.
    """
    from yoke_core.domain.qa_plan_execution_result_state import plan_order

    recorded: list[dict[str, Any]] = []
    skipped: list[str] = []
    for ordinal in range(after_ordinal + 1, len(requirements)):
        requirement = requirements[ordinal]
        if ordinal in done_ordinals or not is_host_free_case(requirement):
            continue
        requirement_id = int(requirement["requirement_id"])
        try:
            check_in()
        except Exception as exc:
            skipped.append(
                f"check-in refused before requirement {requirement_id}: {exc}"
            )
            break
        try:
            result = execute_case(requirement)
        except Exception as exc:
            skipped.append(f"requirement {requirement_id} raised: {exc}")
            continue
        if int(result.get("requirement_id") or 0) != requirement_id:
            skipped.append(
                f"requirement {requirement_id}: the case runner returned a "
                "different requirement"
            )
            continue
        normalized = {**plan_order(requirement), **result}
        try:
            record_result(ordinal, normalized)
        except Exception as exc:
            skipped.append(f"requirement {requirement_id} was not recorded: {exc}")
            break
        done_ordinals.add(ordinal)
        recorded.append(normalized)
    return recorded, skipped


def waiting_recovery(
    recovery: str | None, recorded: list[dict[str, Any]], skipped: list[str]
) -> str | None:
    """The park instruction, prefixed with what ran while the plan queued."""
    if not recorded and not skipped:
        return recovery
    parts = []
    if recorded:
        named = ", ".join(str(row["requirement_id"]) for row in recorded)
        parts.append(
            f"Ran and recorded host-free case requirements {named} while "
            "queued; resume does not rerun them."
        )
    if skipped:
        parts.append(
            "Host-free cases left for the in-order walk on resume: "
            + "; ".join(skipped)
            + "."
        )
    return " ".join([*parts, recovery or ""]).strip()


__all__ = [
    "HOST_FREE_RUNNERS",
    "is_host_free_case",
    "run_host_free_cases_while_waiting",
    "waiting_recovery",
]
