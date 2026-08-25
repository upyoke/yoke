"""Unit tests for https doctor LOCAL+relay composition helpers."""

from __future__ import annotations

from yoke_cli.commands.adapters.doctor_https_compose import (
    false_na_local_runtime_slugs,
    false_na_source_slugs,
    merge_relayed_with_local,
    recount,
)


def test_false_na_local_runtime_slugs_selects_machine_checks() -> None:
    rows = [
        {
            "hc": "HC-session-relay",
            "severity": "N/A",
            "detail": "declared for the local runtime; this run is hosted",
        },
        {
            "hc": "HC-status-consistency",
            "severity": "N/A",
            "detail": "unrelated",
        },
    ]

    assert false_na_local_runtime_slugs(rows) == ["session-relay"]


def test_false_na_source_slugs_filters_checkout_gaps() -> None:
    rows = [
        {
            "hc": "HC-file-line-limit",
            "severity": "N/A",
            "detail": "reads the 1 source tree; this runner has no checkout for it (hosted runtime)",
        },
        {
            "hc": "HC-status-consistency",
            "severity": "PASS",
            "detail": "",
        },
        {
            "hc": "HC-worktree-health",
            "severity": "N/A",
            "detail": "something else",
        },
        {
            # Older server builds still N/A snapshot HCs with the checkout
            # detail even after this client reclassified them as DB-only.
            "hc": "HC-architecture-unclassified-path",
            "severity": "N/A",
            "detail": "reads the 1 source tree; this runner has no checkout for it (hosted runtime)",
        },
    ]
    assert false_na_source_slugs(rows) == [
        "file-line-limit",
        "architecture-unclassified-path",
    ]


def test_merge_replaces_false_na_with_local_verdict() -> None:
    relayed = [
        {
            "hc": "HC-file-line-limit",
            "name": "Authored file 350-line limit",
            "severity": "N/A",
            "detail": "reads the yoke source tree; this runner has no checkout for it (hosted runtime)",
        },
        {
            "hc": "HC-status-consistency",
            "name": "Status consistency",
            "severity": "PASS",
            "detail": "",
        },
    ]
    local = [
        {
            "hc": "HC-file-line-limit",
            "name": "Authored file 350-line limit",
            "severity": "PASS",
            "detail": "",
        },
    ]
    merged = merge_relayed_with_local(relayed, local)
    by_hc = {row["hc"]: row for row in merged}
    assert by_hc["HC-file-line-limit"]["severity"] == "PASS"
    assert by_hc["HC-status-consistency"]["severity"] == "PASS"
    assert recount(merged)["pass_count"] == 2
    assert recount(merged)["na_count"] == 0
