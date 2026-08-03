"""``yoke qa ...`` subcommand registry rows.

Split from :mod:`yoke_cli.commands.registry` so that module stays inside
the authored-file line budget. Same entry shape: CLI token tuple ->
``(function_id, adapter)``.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands.adapters import qa as _qa
from yoke_cli.commands.adapters import qa_browser as _qa_browser
from yoke_cli.commands.adapters import qa_crud as _qa_crud
from yoke_cli.commands.adapters import qa_read as _qa_read

AdapterFn = Callable[[List[str]], int]

QA_SUBCOMMAND_REGISTRY: Dict[Tuple[str, ...], Tuple[str, AdapterFn]] = {
    ("qa", "requirement", "update"): (
        "qa.requirement.update",
        _qa.qa_requirement_update,
    ),
    ("qa", "requirement", "waive"): (
        "qa.requirement.waive",
        _qa.qa_requirement_waive,
    ),
    ("qa", "run", "record-verdict"): (
        "qa.run.record_verdict",
        _qa.qa_run_record_verdict,
    ),
    ("qa", "browser-context", "get"): (
        "qa.browser_context.get",
        _qa_browser.qa_browser_context_get,
    ),
    ("qa", "run", "add"): ("qa.run.add", _qa_browser.qa_run_add),
    ("qa", "run", "complete"): ("qa.run.complete", _qa_browser.qa_run_complete),
    ("qa", "artifact", "add"): ("qa.artifact.add", _qa_browser.qa_artifact_add),
    ("qa", "artifact", "presign"): (
        "qa.artifact.presign",
        _qa_browser.qa_artifact_presign,
    ),
    ("qa", "requirement", "list"): (
        "qa.requirement.list",
        _qa_read.qa_requirement_list,
    ),
    ("qa", "requirement", "get"): ("qa.requirement.get", _qa_read.qa_requirement_get),
    ("qa", "requirement", "add"): ("qa.requirement.add", _qa_crud.qa_requirement_add),
    ("qa", "requirement", "add-batch"): (
        "qa.requirement.add_batch",
        _qa_crud.qa_requirement_add_batch,
    ),
    ("qa", "run", "list"): ("qa.run.list", _qa_read.qa_run_list),
    ("qa", "run", "get"): ("qa.run.get", _qa_read.qa_run_get),
    ("qa", "gate-summary"): ("qa.gate_summary.run", _qa_read.qa_gate_summary),
}

__all__ = ["QA_SUBCOMMAND_REGISTRY"]
