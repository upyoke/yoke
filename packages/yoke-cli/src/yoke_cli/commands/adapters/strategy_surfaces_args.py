"""Argument configuration for strategy review and execution adapters."""

import argparse

from yoke_contracts.project_contract.strategy_doc_fields import fields_recipe

_SLUG_HELP = "Strategy document slug."


def _diff_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("slug", help=_SLUG_HELP)
    parser.add_argument(
        "--from-revision", type=int, required=True, help="Older revision number."
    )
    parser.add_argument(
        "--to-revision", type=int, required=True, help="Newer revision number."
    )


def _restore_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("slug", help=_SLUG_HELP)
    parser.epilog = (
        fields_recipe()
        + " Restore accepts optional --summary / --state to repair an invalid historical revision."
    )
    parser.add_argument("--summary", help="Summary to use in place of the stored one.")
    parser.add_argument("--state", help="State to use in place of the stored one.")
    parser.add_argument(
        "--revision", type=int, required=True, help="Revision number to restore."
    )
    parser.add_argument(
        "--base-updated-at",
        required=True,
        help="Document updated_at you read; a newer edit refuses the restore.",
    )


def _parent_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("slug", help=_SLUG_HELP)
    parent = parser.add_mutually_exclusive_group(required=True)
    parent.add_argument("--parent-slug", help="Slug of the new parent document.")
    parent.add_argument("--clear", action="store_true", help="Remove the parent.")


def _coordination_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("slug", help=_SLUG_HELP)
    parser.add_argument("--section", required=True, help="Section to append to.")
    parser.add_argument("--entry", required=True, help="Entry text to append.")


def _link_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--slug", required=True, help="Strategy document slug to link.")
    parser.add_argument(
        "--document-project",
        help="Project that owns the document; default: the item's.",
    )


def _doc_claim_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("slug", help=_SLUG_HELP)
    parser.add_argument("--reason", help="Why you take or release the claim.")
