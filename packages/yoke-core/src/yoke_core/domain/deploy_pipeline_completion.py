"""Completion notifications emitted by deployment pipeline outcomes."""

from yoke_core.domain import deployment_approval_requests


def notify_failure(run_id: str) -> None:
    deployment_approval_requests.notify_latest_deployment_completion(
        run_id,
        "DeploymentRunFailed",
        "Deployment run failed",
    )


def notify_success(run_id: str) -> None:
    deployment_approval_requests.notify_latest_deployment_completion(
        run_id,
        "DeploymentRunSucceeded",
        "Deployment run completed",
    )


__all__ = ["notify_failure", "notify_success"]
