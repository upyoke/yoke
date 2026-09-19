"""Persist what one Browser QA step captured, and say what it was.

A capture is only evidence if a later reader can tell which screen it is of.
The step's own account of the page — the width it was actually measured at
and the url it was actually on — travels with the bytes, because the route
and the viewport the case *asked for* are requests: metadata rebuilt from the
request can never disagree with it, and a capture of the wrong screen then
reads as a product defect rather than a harness one.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from yoke_contracts.api.function_call import ActorContext
from yoke_core.domain.qa_artifacts import build_metadata


@dataclass
class StepArtifacts:
    """What one step's captures produced, and why any of it failed."""

    paths: List[str] = field(default_factory=list)
    artifact_ids: List[int] = field(default_factory=list)
    recorded: bool = False
    failures: str = ""


def record_step_artifacts(
    *,
    artifact_paths: List[Any],
    step_index: int,
    screenshot_expected: bool,
    run_id: int,
    requirement_id: int,
    qa_kind: str,
    subject: int | str,
    route: str,
    label: Any,
    viewport: Optional[Dict[str, int]],
    observed_url: str,
    actor: Optional[ActorContext] = None,
) -> StepArtifacts:
    """Submit each capture of one step durably and describe the outcome."""
    from yoke_core.domain import browser_qa as _bqa

    outcome = StepArtifacts()
    for artifact_path in artifact_paths:
        if not os.path.isfile(str(artifact_path)):
            if screenshot_expected:
                # A screenshot step that names a file nobody wrote has
                # produced no evidence at all.
                _bqa._log(
                    f"  Step {step_index}: FAILED -- artifact not on disk: "
                    f"{artifact_path}"
                )
                outcome.failures += f"step_{step_index}:artifact_not_on_disk;"
            else:
                _bqa._log(f"  SKIPPED artifact (not on disk): {artifact_path}")
            continue

        metadata = build_metadata(
            step_index,
            qa_kind,
            subject,
            route,
            label,
            viewport=viewport,
            observed_url=observed_url,
        )
        try:
            artifact_id = _bqa._record_artifact_file(
                run_id, requirement_id, str(artifact_path), "image/png",
                "screenshot", json.dumps(metadata), actor=actor,
            )
        except _bqa.QaArtifactWriteError as exc:
            _bqa._log(
                f"  Step {step_index}: FAILED -- durable artifact storage: {exc}"
            )
            outcome.failures += (
                f"step_{step_index}:artifact_storage_failed:{exc};"
            )
            continue
        if artifact_id:
            # Capture scratch remains available for in-session inspection;
            # the recorded evidence already lives in durable storage, and the
            # registered id is the only handle a later reviewer can turn back
            # into readable bytes.
            outcome.paths.append(os.path.abspath(str(artifact_path)))
            outcome.artifact_ids.append(int(artifact_id))
            outcome.recorded = True
    return outcome


__all__ = ["StepArtifacts", "record_step_artifacts"]
