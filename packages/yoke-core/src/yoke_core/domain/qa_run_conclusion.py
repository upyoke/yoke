"""A CI check's proof is the run conclusion, not a screenshot.

A passing ``ci_run`` (or ``github-actions``) row often holds no
``qa_artifacts``. The recorded fact is still there: which SHA the run
verified, and which GitHub Actions run concluded. Readers name that
conclusion and link the run. They do not invent an artifact to fill a
display, and they do not treat an ``agent`` review's ``capture_run_id`` as
an evidence gap — that pointer already names the capture that holds the
screenshots.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

_ACTIONS_RUN = re.compile(
    r"^https://github(?:\.com|\.test)/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+"
    r"/actions/runs/\d+/?$"
)
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _payload(raw_result: Any) -> dict[str, Any]:
    if isinstance(raw_result, dict):
        return raw_result
    if raw_result in (None, ""):
        return {}
    try:
        parsed = json.loads(str(raw_result))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _actions_run_url(payload: Mapping[str, Any]) -> str:
    url = str(payload.get("run_url") or "").strip()
    if _ACTIONS_RUN.match(url):
        return url.rstrip("/")
    repo = str(payload.get("repo") or "").strip()
    run_id = str(payload.get("ci_run_id") or "").strip()
    if _REPO.match(repo) and run_id.isdigit():
        return f"https://github.com/{repo}/actions/runs/{run_id}"
    return ""


def _head_sha(payload: Mapping[str, Any]) -> str:
    for key in ("verification_tree", "code_identity"):
        identity = payload.get(key)
        if not isinstance(identity, dict):
            continue
        sha = str(identity.get("head_sha") or identity.get("sha") or "").strip()
        if sha:
            return sha
    return ""


def run_conclusion_fields(raw_result: Any) -> dict[str, str]:
    """Return the openable CI conclusion, or empty strings when there is none.

    Presence of ``ci_run_id``, ``ci_conclusion``, or a GitHub Actions
    ``run_url`` marks a CI conclusion. ``verification_tree`` alone does not
    — worktree command runs record a SHA too, and their proof is the
    attached output, not this link.
    """
    payload = _payload(raw_result)
    url = _actions_run_url(payload)
    conclusion = str(payload.get("ci_conclusion") or "").strip()
    ci_run_id = str(payload.get("ci_run_id") or "").strip()
    if not (url or conclusion or ci_run_id):
        return {"run_url": "", "ci_conclusion": ""}
    return {"run_url": url, "ci_conclusion": conclusion}


def conclusion_proof_summary(raw_result: Any) -> str | None:
    """Name the CI conclusion as the current proof, or None when it is not CI."""
    fields = run_conclusion_fields(raw_result)
    if not fields["run_url"] and not fields["ci_conclusion"]:
        return None
    sha = _head_sha(_payload(raw_result))[:12]
    if sha:
        return f"verified {sha} · GitHub Actions run"
    return "GitHub Actions run conclusion"


__all__ = [
    "conclusion_proof_summary",
    "run_conclusion_fields",
]
