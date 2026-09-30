"""Argument configuration for strategy review and execution adapters."""

import argparse

from yoke_contracts.project_contract.strategy_doc_fields import fields_recipe


def _diff_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("slug")
    parser.add_argument("--from-revision", type=int, required=True)
    parser.add_argument("--to-revision", type=int, required=True)


def _restore_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("slug")
    parser.epilog = (
        fields_recipe()
        + " Restore accepts optional --summary / --state to repair an invalid historical revision."
    )
    parser.add_argument("--summary")
    parser.add_argument("--state")
    parser.add_argument("--revision", type=int, required=True)
    parser.add_argument("--base-updated-at", required=True)


def _parent_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("slug")
    parent = parser.add_mutually_exclusive_group(required=True)
    parent.add_argument("--parent-slug")
    parent.add_argument("--clear", action="store_true")


def _coordination_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("slug")
    parser.add_argument("--section", required=True)
    parser.add_argument("--entry", required=True)


def _link_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--slug", required=True)
    parser.add_argument("--document-project")


def _doc_claim_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("slug")
    parser.add_argument("--reason")
