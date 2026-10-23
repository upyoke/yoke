"""Argument configuration for strategy review and execution adapters."""

import argparse

from yoke_contracts.project_contract.strategy_doc_fields import field_heading

_SLUG_HELP = "Strategy document slug."


def _diff_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("slug", help=_SLUG_HELP)
    parser.add_argument(
        "--from-revision", type=int, required=True, metavar="N", help="Older revision number."
    )
    parser.add_argument(
        "--to-revision", type=int, required=True, metavar="N", help="Newer revision number."
    )


def _restore_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("slug", help=_SLUG_HELP)
    parser.epilog = (
        "Use --summary and --state to repair an old revision whose "
        f"{field_heading('Summary')} or {field_heading('State')} section is "
        "missing or invalid."
    )
    parser.add_argument(
        "--summary", metavar="TEXT", help="Summary to use in place of the stored one."
    )
    parser.add_argument(
        "--state", metavar="TEXT", help="State to use in place of the stored one."
    )
    parser.add_argument(
        "--revision", type=int, required=True, metavar="N", help="Revision number to restore."
    )
    parser.add_argument(
        "--base-updated-at",
        required=True,
        metavar="TS",
        help="Document updated_at you read; a newer edit refuses the restore.",
    )


def _parent_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("slug", help=_SLUG_HELP)
    parent = parser.add_mutually_exclusive_group(required=True)
    parent.add_argument(
        "--parent-slug", metavar="PARENT", help="Slug of the new parent document."
    )
    parent.add_argument("--clear", action="store_true", help="Remove the parent.")


def _coordination_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("slug", help=_SLUG_HELP)
    parser.add_argument(
        "--section", required=True, metavar="NAME", help="Section to append to."
    )
    parser.add_argument(
        "--entry", required=True, metavar="TEXT", help="Entry text to append."
    )


def _link_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--slug", required=True, metavar="SLUG", help="Strategy document slug to link."
    )
    parser.add_argument(
        "--document-project",
        metavar="P",
        help="Project that owns the document; default: the item's.",
    )


def _doc_claim_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("slug", help=_SLUG_HELP)
    parser.add_argument("--reason", metavar="TEXT", help="Why you take or release the claim.")
