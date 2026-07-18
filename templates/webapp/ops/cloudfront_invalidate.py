#!/usr/bin/env python3
"""Fail-closed CloudFront distribution validation and cache invalidation."""

from __future__ import annotations

from collections.abc import Sequence
import subprocess
import sys


MAX_DIAGNOSTIC_CHARS = 2000


def _run_aws(command: Sequence[str], failure_message: str) -> str:
    result = subprocess.run(
        command,
        capture_output=True,
        check=False,
        text=True,
    )
    output = f"{result.stdout}{result.stderr}".strip()
    if result.returncode:
        print(
            f"{failure_message} (exit {result.returncode})",
            file=sys.stderr,
        )
        if output:
            print(output[-MAX_DIAGNOSTIC_CHARS:], file=sys.stderr)
        raise SystemExit(result.returncode)
    return result.stdout.strip()


def invalidate_distribution(distribution_id: str) -> None:
    selected_id = distribution_id.strip()
    if not selected_id or selected_id == "TODO":
        raise SystemExit("CloudFront distribution ID is not configured")

    distribution = _run_aws(
        (
            "aws",
            "cloudfront",
            "list-distributions",
            "--query",
            f"DistributionList.Items[?Id=='{selected_id}'].[Id,DomainName,Status]",
            "--output",
            "text",
        ),
        "CloudFront distribution discovery failed",
    )
    if not distribution or distribution == "None":
        raise SystemExit(f"CloudFront distribution {selected_id} was not found")
    print(f"CloudFront distribution: {distribution}")

    invalidation = _run_aws(
        (
            "aws",
            "cloudfront",
            "create-invalidation",
            "--distribution-id",
            selected_id,
            "--paths",
            "/*",
            "--query",
            "Invalidation.[Id,Status]",
            "--output",
            "text",
        ),
        "CloudFront invalidation failed",
    )
    print(f"CloudFront invalidation: {invalidation}")


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print("usage: cloudfront_invalidate.py DISTRIBUTION_ID", file=sys.stderr)
        return 2
    invalidate_distribution(args[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
