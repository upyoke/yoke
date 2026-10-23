"""Read source-proven QA case input without writing through an older server."""

import argparse
import json
import sys
from pathlib import Path

from yoke_contracts.api.function_call import TargetRef
from yoke_cli.commands._helpers import ensure_handlers_loaded
from yoke_cli.commands.adapters.qa_catalog_usage import PLAN_CASES_REPLACE_EPILOG
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher


def case_payload(parsed):
    raw = sys.stdin.read() if parsed.stdin else Path(parsed.cases_file).read_text()
    document = json.loads(raw)
    revision = parsed.source_revision
    if isinstance(document, dict):
        if (
            set(document) != {"source_revision", "cases"}
            or not document["source_revision"]
        ):
            raise ValueError(
                "qa_plan_source_document_invalid: export a document with source_revision and cases"
            )
        if revision is not None and revision != document["source_revision"]:
            raise ValueError(
                "qa_plan_source_revision_conflict: use the export's recorded source revision; do not relabel its case definitions"
            )
        revision = document["source_revision"]
        cases = document["cases"]
    else:
        cases = document
    if not isinstance(cases, list):
        raise ValueError("cases input must be a JSON array")
    result = {"plan_id": parsed.plan_id, "cases": cases}
    if revision is not None:
        ensure_handlers_loaded()
        receipt = call_dispatcher(
            function_id="qa.plan.get",
            target=TargetRef(kind="global"),
            payload={
                "project": parsed.project,
                "plan_id": parsed.plan_id,
                "detail": "full",
            },
            actor=build_actor(session_id=parsed.session_id),
        )
        if not receipt.success:
            raise ValueError(
                f"qa_plan_source_read_failed: {receipt.error}; restore plan read access before syncing"
            )
        if "source_revision" not in (receipt.result or {}).get("plan", {}):
            raise ValueError(
                "qa_plan_source_binding_unavailable: source-proven sync requires the "
                "serving release carrying qa_plans.source_revision and boot convergence; "
                "ask the control-plane operator to serve it before syncing. No cases were written."
            )
        result["source_revision"] = revision
    return result


def configure_case_replace(parser: argparse.ArgumentParser) -> None:
    parser.epilog = PLAN_CASES_REPLACE_EPILOG
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    parser.add_argument(
        "--plan-id",
        type=int,
        required=True,
        help="QA plan whose cases to replace.",
    )
    parser.add_argument(
        "--source-revision",
        help="Full merged source SHA from the case exporter; binds release QA to this revision.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--cases-file", help="JSON file with the full case list.")
    source.add_argument(
        "--stdin",
        action="store_true",
        help="Read the case list JSON from stdin.",
    )
