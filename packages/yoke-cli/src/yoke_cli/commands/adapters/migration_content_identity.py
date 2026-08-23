"""CLI adapter for semantic migration-content identity verification."""

from __future__ import annotations

import argparse
import json
from typing import List

from pydantic import ValidationError

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.migration_content_identity import (
    FUNCTION_ID,
    MigrationContentIdentityVerifyRequest,
)


VERIFY_USAGE = (
    "yoke migration content-identity verify --entries-json JSON "
    "[--session-id S] [--json]"
)


def migration_content_identity_verify(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke migration content-identity verify",
        description=(
            "Compare candidate migration name/digest entries with the fixed "
            "control-plane ledger. The response never exposes ledger digests."
        ),
    )
    parser.add_argument(
        "--entries-json",
        required=True,
        help="JSON array of {name, content_sha256} candidate entries.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, VERIFY_USAGE)
    if parsed is None:
        return 2
    try:
        entries = json.loads(parsed.entries_json)
        spec = MigrationContentIdentityVerifyRequest.model_validate(
            {"entries": entries}
        )
    except (ValueError, ValidationError):
        return usage_error(
            "--entries-json must be a non-empty JSON array with unique names "
            "and SHA256 digests"
        )
    return dispatch_and_emit(
        function_id=FUNCTION_ID,
        target=TargetRef(kind="global"),
        payload=spec.model_dump(mode="json"),
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = [
    "VERIFY_USAGE",
    "migration_content_identity_verify",
]
