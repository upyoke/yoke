"""Delivery-point arguments shared by instruction creation and edits."""

import argparse


def _delivery_args(parser: argparse.ArgumentParser) -> None:
    for flag, label in (
        ("before-creation", "Before creation"),
        ("on-every-read", "On every read"),
        ("when-entering-stage", "When entering stage"),
    ):
        parser.add_argument(
            f"--{flag}",
            action=argparse.BooleanOptionalAction,
            default=None,
            help=f"Enable/disable {label}; omitted settings are preserved.",
        )
    parser.add_argument(
        "--stage-bucket",
        action="append",
        dest="stage_buckets",
        help="Stage target: idea, planning, refined, implementing, reviewing, implemented, release; repeatable.",
    )
    parser.add_argument(
        "--clear-stage-buckets",
        action="store_true",
        help="Clear targets (disable When entering stage in the same edit).",
    )


def _delivery_payload(parsed: argparse.Namespace) -> dict:
    fields = (
        "before_creation",
        "on_every_read",
        "when_entering_stage",
        "stage_buckets",
    )
    result = {
        key: getattr(parsed, key) for key in fields if getattr(parsed, key) is not None
    }
    if parsed.clear_stage_buckets:
        result["stage_buckets"] = []
    return result
