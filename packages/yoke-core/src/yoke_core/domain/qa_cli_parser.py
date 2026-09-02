"""QA CLI parser construction."""

from __future__ import annotations

import argparse
from yoke_core.domain.cli_text_file import add_text_file_pair
from yoke_core.domain.qa_gate_summary import (
    register_subparser as _register_gate_summary,
)
from yoke_core.domain import qa_requirement_policy_validation as _qap
from yoke_core.domain.qa_undetermined_evidence import UNDETERMINED_VERDICT_HELP


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.qa", description="QA domain CRUD"
    )
    sub = p.add_subparsers(dest="subcmd")

    sub.add_parser("init")

    ra = sub.add_parser("requirement-add")
    ra.add_argument("--item-id", type=int)
    ra.add_argument("--epic-id", type=int)
    ra.add_argument("--task-num", type=int)
    ra.add_argument("--deployment-run-id")
    ra.add_argument("--qa-kind", required=True, help=_qap.QA_KIND_HELP)
    ra.add_argument("--qa-phase", required=True)
    ra.add_argument("--target-env")
    ra.add_argument("--blocking-mode", default="blocking")
    ra.add_argument(
        "--requirement-source",
        choices=_qap.VALID_REQUIREMENT_SOURCES,
        default="explicit",
        help=_qap.REQUIREMENT_SOURCE_HELP,
    )
    ra.add_argument("--success-policy", help=_qap.SUCCESS_POLICY_HELP)
    ra.add_argument(
        "--required-capability",
        dest="capability_requirements",
        action="append",
        help="Required capability kind; repeat for more than one.",
    )
    ra.add_argument("--suite-id")
    ra.add_argument(
        "--workflow-transition",
        "--workflow-transition-id",
        dest="workflow_transition_id",
        help=("Pinned workflow stage that owns this item/epic QA requirement."),
    )

    rab = sub.add_parser("requirement-add-batch")
    rab.add_argument(
        "--json-file", required=True, help="Path to JSON array of requirement objects"
    )

    rl = sub.add_parser("requirement-list")
    rl.add_argument("--item-id", type=int)
    rl.add_argument("--epic-id", type=int)
    rl.add_argument("--deployment-run-id")

    rg = sub.add_parser("requirement-get")
    rg.add_argument("id", type=int)

    ru = sub.add_parser(
        "requirement-update",
        help="Update a mutable field on an existing QA requirement.",
    )
    ru.add_argument("id", type=int)
    ru.add_argument(
        "field",
        help=(
            "Field to update. Allowed: success_policy, blocking_mode, target_env, "
            "capability_requirements, suite_id, qa_phase. qa_kind is NOT updatable; "
            "use requirement-waive + requirement-add to change the verification surface."
        ),
    )
    ru_value = ru.add_mutually_exclusive_group()
    ru_value.add_argument(
        "value",
        nargs="?",
        help="Literal value to write. Use --stdin or --body-file for JSON or multi-line values.",
    )
    ru_value.add_argument(
        "--stdin",
        action="store_true",
        help="Read the value from standard input (preferred for success_policy JSON).",
    )
    ru_value.add_argument(
        "--body-file",
        help="Read the value from a file.",
    )

    rw = sub.add_parser("requirement-waive")
    rw.add_argument("id", type=int)
    rw.add_argument("rationale")
    rw.add_argument("--source", default="agent")
    rw.add_argument("--force", action="store_true")

    rna = sub.add_parser("run-add", epilog=UNDETERMINED_VERDICT_HELP)
    rna.add_argument("--requirement-id", type=int, required=True)
    rna.add_argument("--performed-by", required=True)
    rna.add_argument(
        "--qa-kind",
        help=(
            "Optional. Defaults to the matching qa_requirements row's "
            "qa_kind; supplying a different value is a hard error."
        ),
    )
    rna.add_argument("--verdict")
    rna.add_argument("--verdict-reason", help=UNDETERMINED_VERDICT_HELP)
    rna.add_argument(
        "--execution-status",
        choices=("captured", "capture_failed"),
        help="Browser capture outcome, distinct from quality verdict.",
    )
    rna.add_argument("--score", type=float)
    rna.add_argument("--confidence", type=float)
    rna_raw = rna.add_mutually_exclusive_group()
    add_text_file_pair(rna_raw, "--raw-result", "--raw-result-file", dest="raw_result")
    rna.add_argument("--duration-ms", type=int)
    rna.add_argument(
        "--head-sha",
        help=(
            "Commit the run verified. Default: stamp the claimed lane HEAD "
            "on a clean tree. Required when no lane resolves."
        ),
    )
    rna.add_argument(
        "--artifact-path",
        help=(
            "Optional screenshot path; creates a linked qa_artifact automatically "
            "and canonicalizes item-backed files into scratch-backed QA storage."
        ),
    )

    rnab = sub.add_parser("run-add-batch", epilog=UNDETERMINED_VERDICT_HELP)
    rnab.add_argument(
        "--json-file", required=True, help="Path to JSON array of run objects"
    )

    rc = sub.add_parser("run-complete", epilog=UNDETERMINED_VERDICT_HELP)
    rc.add_argument("--run-id", type=int, required=True)
    rc.add_argument("--verdict")
    rc.add_argument("--verdict-reason", help=UNDETERMINED_VERDICT_HELP)
    rc.add_argument(
        "--execution-status",
        choices=("captured", "capture_failed"),
        help="Browser capture outcome, distinct from quality verdict.",
    )
    rc_raw = rc.add_mutually_exclusive_group()
    add_text_file_pair(rc_raw, "--raw-result", "--raw-result-file", dest="raw_result")
    rc.add_argument("--duration-ms", type=int)

    rnl = sub.add_parser("run-list")
    rnl.add_argument("--requirement-id", type=int)

    rng = sub.add_parser("run-get")
    rng.add_argument("id", type=int)

    aa = sub.add_parser("artifact-add")
    aa.add_argument("--run-id", type=int)
    aa.add_argument("--artifact-type", required=True)
    aa.add_argument("--content-type")
    aa.add_argument(
        "--artifact-handle",
        help='Typed handle JSON ({"backend":"s3"|"local",...}); bare paths are refused.',
    )
    aa.add_argument("--metadata")

    # artifact-list
    al = sub.add_parser("artifact-list")
    al.add_argument("--run-id", type=int)
    al.add_argument(
        "--item-id",
        type=int,
        help="List all artifacts for an item (joins through runs/requirements)",
    )
    al.add_argument(
        "--resolve-addresses",
        action="store_true",
        help="Resolve handles honestly: filesystem path (local), s3://bucket/key URI (s3).",
    )

    # baseline-record
    br = sub.add_parser("baseline-record")
    br.add_argument("--route", required=True)
    br.add_argument("--width", type=int, required=True)
    br.add_argument("--height", type=int, required=True)
    br.add_argument("--branch", default="")
    br.add_argument("--commit", default="")
    br.add_argument("--project")
    br.add_argument("--screenshot-path", required=True)
    br.add_argument("--update", action="store_true")

    # baseline-list
    bl = sub.add_parser("baseline-list")
    bl.add_argument("--project")

    # baseline-get
    bg = sub.add_parser("baseline-get")
    bg.add_argument("route")
    bg.add_argument("viewport")

    # baseline-promote
    bp = sub.add_parser("baseline-promote")
    bp.add_argument("id", type=int)

    _register_gate_summary(sub)

    return p
