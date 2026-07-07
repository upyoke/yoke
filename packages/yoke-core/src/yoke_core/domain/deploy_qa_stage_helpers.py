"""Stage helpers for the deployment QA recorder.

Pure helpers extracted from ``deploy_qa_recorder`` so the orchestrator
module stays under its line budget. The five exported helpers cover:

* script-dir resolution for legacy script-relative invocations,
* subprocess dispatch into ``yoke_core.cli.db_router`` and
  ``yoke_core.domain.flow``,
* parsing flow stage JSON to extract QA-relevant entries,
* resolving the ``qa_kind`` for a single stage by name.

Both subprocess wrappers capture stdout and return it stripped, so callers
branch on an empty ``stdout`` to detect failure. On a non-zero exit they
re-emit the subprocess's own stderr and return code to this process's
stderr before returning the (empty) stdout: the deploy pipeline runs these
helpers in-process, so that diagnostic lands in the deploy log where a
failed ``qa requirement-add`` can actually be root-caused — rather than
being discarded into a captured-but-dropped stderr. A subprocess that
exceeds the dispatch timeout is reported the same way and degrades to an
empty return rather than raising, so a slow control-plane round-trip can
never crash the whole deploy on a best-effort QA write.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

# Per-call wall-clock budget for a single control-plane round-trip. Named so
# both wrappers share one value and the timeout diagnostic can cite it.
DISPATCH_TIMEOUT_S = 30


def resolve_script_dir() -> str:
    """Return the legacy skills/scripts directory used by callers."""
    from yoke_core.api.repo_root import find_repo_root

    return str(find_repo_root(Path(__file__)) / ".agents" / "skills" / "yoke" / "scripts")


def _dispatch_module(module: str, args: List[str]) -> str:
    """Run ``python3 -m <module> <args>`` and return its stripped stdout.

    On failure (non-zero exit or timeout) the underlying subprocess's stderr
    and return code are re-emitted to *this* process's stderr so the real
    cause surfaces in the deploy log; the return value stays the stripped
    stdout (empty on failure) to preserve the empty-means-failure contract
    every caller already branches on.
    """
    cmd = [sys.executable, "-m", module, *args]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=DISPATCH_TIMEOUT_S
        )
    except subprocess.TimeoutExpired:
        print(
            f"  dispatch timeout: python3 -m {module} {' '.join(args)} "
            f"exceeded {DISPATCH_TIMEOUT_S}s — treating as failure",
            file=sys.stderr,
        )
        return ""
    if result.returncode != 0:
        detail = result.stderr.strip()
        print(
            f"  dispatch failure: python3 -m {module} {' '.join(args)} "
            f"exited {result.returncode}"
            + (f"\n{detail}" if detail else " (no stderr captured)"),
            file=sys.stderr,
        )
    return result.stdout.strip()


def dispatch_db_router(*args: str, script_dir: Optional[str] = None) -> str:
    """Subprocess dispatch into the Python DB router.

    Kept as a subprocess boundary (rather than a direct import) so the
    recorder's CLI surface can preserve the event-emission and argument
    parsing that ``yoke_core.cli.db_router`` performs, without taking
    a hard import dependency on every downstream domain module.
    """
    return _dispatch_module("yoke_core.cli.db_router", list(args))


def dispatch_flow_domain(*args: str, script_dir: Optional[str] = None) -> str:
    """Subprocess dispatch into ``yoke_core.domain.flow``.

    Like ``dispatch_db_router`` above, this wrapper is a pure Python
    subprocess boundary — it never dispatches to a shell script.
    """
    return _dispatch_module("yoke_core.domain.flow", list(args))


def parse_stages_qa(stages_json: str) -> List[Dict[str, str]]:
    """Parse flow stages JSON and return QA-relevant entries.

    A stage is QA-relevant if it has an explicit ``qa_kind`` field or
    its name contains ``smoke``.
    """
    stages = json.loads(stages_json)
    qa_stages: List[Dict[str, str]] = []
    for s in stages:
        name = s.get("name", "")
        qa_kind = s.get("qa_kind", "")
        success_policy = s.get("success_policy", "")
        if not qa_kind and "smoke" in name:
            qa_kind = "smoke"
        if qa_kind:
            if not success_policy:
                success_policy = "Workflow completes with conclusion=success"
            qa_stages.append({
                "name": name,
                "qa_kind": qa_kind,
                "success_policy": success_policy,
            })
    return qa_stages


def resolve_qa_kind_for_stage(stages_json: str, stage_name: str) -> str:
    """Resolve the qa_kind for a named stage from the flow config."""
    try:
        stages = json.loads(stages_json)
    except (json.JSONDecodeError, TypeError):
        stages = []
    for s in stages:
        if s.get("name") == stage_name:
            qk = s.get("qa_kind", "")
            if not qk and "smoke" in stage_name:
                qk = "smoke"
            return qk
    # Fallback: infer from name
    if "smoke" in stage_name:
        return "smoke"
    return ""
