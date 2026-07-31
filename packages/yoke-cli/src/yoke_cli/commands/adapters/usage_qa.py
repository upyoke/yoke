"""``qa.*`` function-id → usage-line map.

Split from :mod:`yoke_cli.commands.adapters.usage` so that module stays
inside the authored-file line budget. Merged back into ``ADAPTER_USAGE``.
"""

from __future__ import annotations

from typing import Dict

from yoke_cli.commands.adapters.qa import (
    QA_REQUIREMENT_UPDATE_USAGE,
    QA_RUN_RECORD_VERDICT_USAGE,
)
from yoke_cli.commands.adapters.qa_crud import (
    QA_REQUIREMENT_ADD_BATCH_USAGE,
    QA_REQUIREMENT_ADD_USAGE,
)
from yoke_cli.commands.adapters.qa_read import (
    QA_GATE_SUMMARY_USAGE,
    QA_REQUIREMENT_GET_USAGE,
    QA_REQUIREMENT_LIST_USAGE,
    QA_RUN_GET_USAGE,
    QA_RUN_LIST_USAGE,
)
from yoke_cli.commands.adapters.qa_browser import (
    QA_ARTIFACT_ADD_USAGE,
    QA_ARTIFACT_PRESIGN_USAGE,
    QA_BROWSER_CONTEXT_GET_USAGE,
    QA_RUN_ADD_USAGE,
    QA_RUN_COMPLETE_USAGE,
)

QA_ADAPTER_USAGE: Dict[str, str] = {
    "qa.requirement.update": QA_REQUIREMENT_UPDATE_USAGE,
    "qa.run.record_verdict": QA_RUN_RECORD_VERDICT_USAGE,
    "qa.browser_context.get": QA_BROWSER_CONTEXT_GET_USAGE,
    "qa.run.add": QA_RUN_ADD_USAGE,
    "qa.run.complete": QA_RUN_COMPLETE_USAGE,
    "qa.artifact.add": QA_ARTIFACT_ADD_USAGE,
    "qa.artifact.presign": QA_ARTIFACT_PRESIGN_USAGE,
    "qa.requirement.list": QA_REQUIREMENT_LIST_USAGE,
    "qa.requirement.get": QA_REQUIREMENT_GET_USAGE,
    "qa.requirement.add": QA_REQUIREMENT_ADD_USAGE,
    "qa.requirement.add_batch": QA_REQUIREMENT_ADD_BATCH_USAGE,
    "qa.run.list": QA_RUN_LIST_USAGE,
    "qa.run.get": QA_RUN_GET_USAGE,
    "qa.gate_summary.run": QA_GATE_SUMMARY_USAGE,
}

__all__ = ["QA_ADAPTER_USAGE"]
