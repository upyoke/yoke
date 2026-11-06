"""Read provider reasons for jobs that never obtained a runner.

GitHub's Checks API owns these messages; log downloads do not exist for
jobs that never started. Keep annotation text opaque to recovery policy.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

from yoke_core.domain.gh_rest_transport import RestTransportError


def job_annotations(repo: str, job: Mapping[str, Any], *, token: str) -> list[dict]:
    """Read all annotations, using only a check URL within the bound repo."""
    from yoke_core.domain.github_actions_rest import rest_get

    path = urlsplit(str(job.get("check_run_url") or "")).path
    prefix = f"/repos/{repo}/check-runs/"
    check_id = path.removeprefix(prefix)
    if not path.startswith(prefix) or not check_id.isdecimal():
        raise RestTransportError(
            "ci_job_annotations_unavailable: job has no valid check_run_url; "
            "open its GitHub job page to inspect annotations before retrying"
        )
    annotations = []
    for page in range(1, 51):
        data = rest_get(
            f"{prefix}{check_id}/annotations",
            query={"per_page": "100", "page": str(page)},
            token=token,
        )
        if not isinstance(data, list) or any(
            not isinstance(row, dict)
            or not isinstance(row.get("message"), str)
            or row.get("annotation_level") not in {"notice", "warning", "failure"}
            for row in data
        ):
            raise RestTransportError(
                "ci_job_annotations_unavailable: unreadable Checks response; "
                "restore Checks read access and retry before re-dispatching"
            )
        annotations.extend(
            {
                "job_id": str(job.get("id") or ""),
                "name": str(job.get("name") or ""),
                "annotation_level": row["annotation_level"],
                "message": row["message"],
            }
            for row in data
        )
        if len(data) < 100:
            return annotations
    raise RestTransportError(
        "ci_job_annotations_unavailable: annotation page limit reached; "
        "inspect the job in GitHub before retrying"
    )


def never_started_annotations(
    repo: str, jobs: Sequence[Mapping], *, token: str
) -> list[dict]:
    from yoke_core.domain.ci_job_outcome import job_never_started

    return [
        annotation
        for job in jobs
        if job_never_started(job)
        for annotation in job_annotations(repo, job, token=token)
    ]


def annotation_text(annotations: Sequence[Mapping]) -> str:
    return "\n".join(
        f"{row.get('name') or row.get('job_id')}: "
        f"{row['annotation_level']}: {row['message']}"
        for row in annotations
    )
