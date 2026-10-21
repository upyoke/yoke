"""Every background job the control plane's long-lived process hosts.

Each install mode has one such process: the API server (hosted and
self-hosted), or the standing relay of a machine-local universe, which
dispatches in-process and has no server. Both enter this one context.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator


@contextmanager
def control_plane_background_jobs() -> Iterator[None]:
    """Run the GitHub observation and QA settlement follow-up jobs."""
    from yoke_core.domain.pending_github_observation_job import (
        pending_github_observation_job,
    )
    from yoke_core.domain.qa_settlement_followup_job import (
        qa_settlement_followup_job,
    )

    with pending_github_observation_job(), qa_settlement_followup_job():
        yield


__all__ = ["control_plane_background_jobs"]
