"""Arguments describing a recoverable execution substrate failure."""

import argparse


def configure_skip_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("item", help="Item id (PREFIX-N).")
    parser.add_argument(
        "--chain-step",
        dest="chain_step",
        type=int,
        required=True,
        help="Current checkpoint step number.",
    )
    parser.add_argument(
        "--project", required=True, help="Project id the failing handler is bound to."
    )
    parser.add_argument(
        "--routed-action",
        dest="routed_action",
        required=True,
        help="Routed action that failed (e.g. 'implement').",
    )
    parser.add_argument(
        "--failure-class",
        dest="failure_class",
        required=True,
        help="Structured failure class string.",
    )
    parser.add_argument(
        "--remediation-owner",
        dest="remediation_owner",
        required=True,
        help="Work item id or recipe owner responsible for the fix.",
    )
    parser.add_argument(
        "--current-status",
        dest="current_status",
        default=None,
        help="Lifecycle status of the failing item at skip time.",
    )
    parser.add_argument(
        "--useful-work-began",
        dest="useful_work_began",
        action="store_true",
        default=False,
        help="Set when the routed handler made useful progress before the failure.",
    )
