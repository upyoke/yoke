"""Key folds naming a QA host a test machine inside stored QA documents.

QA documents once named their host ``machine`` (and a simultaneous host set
``machines``); ``machine`` now means only a registered Yoke Machine. Each
fold returns the document unchanged when it already carries the current key,
so a re-run is a no-op and a row holding both keys keeps the current one.
"""

from __future__ import annotations

import json
from typing import Any

#: Retired ``method_config`` key -> current key.
METHOD_CONFIG_KEYS = (("machine", "test_machine"), ("machines", "test_machines"))
#: Retired evidence / artifact metadata key -> current key.
EVIDENCE_KEYS = (("machine", "test_machine"),)
HOST_CONTROL_RUNNER = "host_control"


def fold_keys(document: Any, renames: tuple[tuple[str, str], ...]) -> Any:
    """Rename top-level keys, keeping an existing current key over the old one."""
    if not isinstance(document, dict) or not any(old in document for old, _ in renames):
        return document
    folded = dict(document)
    for old, new in renames:
        if old in folded:
            value = folded.pop(old)
            folded.setdefault(new, value)
    return folded


def fold_method_config(config: Any) -> Any:
    return fold_keys(config, METHOD_CONFIG_KEYS)


def fold_run_result(document: Any) -> Any:
    """Fold a run's start-bound config snapshot and its host-control evidence."""
    if not isinstance(document, dict):
        return document
    folded = dict(document)
    if "method_config" in folded:
        folded["method_config"] = fold_method_config(folded["method_config"])
    evidence = folded.get("evidence")
    if isinstance(evidence, dict) and evidence.get("runner_id") == HOST_CONTROL_RUNNER:
        folded["evidence"] = fold_keys(evidence, EVIDENCE_KEYS)
    return folded


def fold_roster(roster: Any) -> Any:
    """Fold every frozen case's ``method_config`` in an execution roster."""
    if not isinstance(roster, list):
        return roster
    return [
        {**case, "method_config": fold_method_config(case["method_config"])}
        if isinstance(case, dict) and "method_config" in case
        else case
        for case in roster
    ]


def fold_artifact_metadata(metadata: Any) -> Any:
    """Fold the test machine an artifact's metadata names."""
    if isinstance(metadata, dict) and isinstance(metadata.get("machine"), str):
        return fold_keys(metadata, EVIDENCE_KEYS)
    return metadata


def parsed(raw: Any) -> Any:
    """Decode one stored JSON text; text that is not JSON is left alone."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def compact(value: Any) -> str:
    """The sorted compact JSON form QA writers store and readers compare."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


__all__ = [
    "compact",
    "fold_artifact_metadata",
    "fold_keys",
    "fold_method_config",
    "fold_roster",
    "fold_run_result",
    "parsed",
]
