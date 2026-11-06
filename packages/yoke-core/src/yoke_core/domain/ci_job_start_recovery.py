"""Stop CI recovery for a provider refusal before spending a retry."""

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher

OPERATOR_REQUIRED = "ci_job_not_started_requires_operator"
ANNOTATIONS_UNAVAILABLE = "ci_job_annotations_unavailable"


def recovery_blocked(output: str) -> bool:
    return OPERATOR_REQUIRED in output or ANNOTATIONS_UNAVAILABLE in output


def ask_operator(*, repo: str, run_id: str, output: str, actor=None) -> str:
    """File one session question per run, preserving the provider's words."""
    question = (
        f"GitHub could not start CI run {run_id} in {repo}. "
        f"Please resolve its annotation before retrying.\n{output[:1700]}"
    )
    context = output if len(output) <= 7900 else output[:7900] + "\n[truncated; open the run for all annotations]"
    try:
        response = call_dispatcher(
            function_id="decision_requests.ask", target=TargetRef(kind="global"),
            actor=actor,
            payload={"key": f"ci-job-start-{run_id}", "question": question,
                     "context": context},
        )
        if response.success:
            return f"{OPERATOR_REQUIRED}: operator question filed; no re-dispatch.\n{output}"
        detail = getattr(response.error, "message", "question filing refused")
    except Exception as exc:  # noqa: BLE001 - preserve the original refusal
        detail = str(exc)
    return (
        f"ci_job_start_question_failed: {detail}; ask the operator to inspect "
        f"https://github.com/{repo}/actions/runs/{run_id} before retrying.\n{output}"
    )
