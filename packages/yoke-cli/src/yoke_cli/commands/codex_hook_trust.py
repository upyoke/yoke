"""Machine-local ownership for Codex's path-keyed hook trust."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from typing import Callable, Dict, List, Tuple

from yoke_cli.commands._helpers import parse_or_usage_error


AdapterFn = Callable[[List[str]], int]

CODEX_HOOK_TRUST_SWEEP_USAGE = "yoke codex hook-trust sweep [--dry-run] [--json]"


def codex_hook_trust_sweep(args: List[str]) -> int:
    """Drop trust entries whose literal hooks or project paths are gone."""
    parser = argparse.ArgumentParser(
        prog="yoke codex hook-trust sweep",
        description=(
            f"{CODEX_HOOK_TRUST_SWEEP_USAGE}\n\n"
            "Remove Codex hook-trust and project tables only when their "
            "absolute filesystem paths no longer exist. Existing paths and "
            "unrecognized third-party entries are preserved."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report stale counts without changing Codex config.",
    )
    parser.add_argument(
        "--json",
        dest="json_mode",
        action="store_true",
        help="Emit a machine-readable count receipt.",
    )
    parsed = parse_or_usage_error(parser, args, CODEX_HOOK_TRUST_SWEEP_USAGE)
    if parsed is None:
        return 2

    trust_store = importlib.import_module("yoke_core.domain.codex_hook_trust_store")
    try:
        receipt = trust_store.sweep_stale_trust(dry_run=parsed.dry_run)
    except trust_store.CodexHookTrustStoreError as exc:
        recovery = (
            f"repair the named Codex config, then rerun `{trust_store.SWEEP_COMMAND}`"
        )
        payload = {
            "error": "codex_hook_trust_sweep_refused",
            "detail": str(exc),
            "ok": False,
            "operation": "codex.hook_trust.sweep",
            "recovery": recovery,
        }
        if parsed.json_mode:
            print(json.dumps(payload, sort_keys=True), file=sys.stderr)
        else:
            print(
                f"Codex hook trust sweep refused: {exc}. Recovery: {recovery}.",
                file=sys.stderr,
            )
        return 1

    payload = {
        **receipt.payload(),
        "ok": True,
        "operation": "codex.hook_trust.sweep",
    }
    if parsed.json_mode:
        print(json.dumps(payload, sort_keys=True))
        return 0
    if receipt.skipped_reason:
        print(f"Codex hook trust sweep skipped: {receipt.skipped_reason}.")
        return 0
    verb = "Would remove" if receipt.dry_run else "Removed"
    print(
        f"{verb} {receipt.hook_entries_removed} hook trust entries across "
        f"{receipt.stale_hook_paths} deleted hooks paths and "
        f"{receipt.project_entries_removed} deleted project entries."
    )
    return 0


TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("codex", "hook-trust", "sweep"): codex_hook_trust_sweep,
}

TOOL_SHAPED_USAGE: Dict[str, str] = {
    "yoke codex hook-trust sweep": CODEX_HOOK_TRUST_SWEEP_USAGE,
}


__all__ = [
    "CODEX_HOOK_TRUST_SWEEP_USAGE",
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "codex_hook_trust_sweep",
]
