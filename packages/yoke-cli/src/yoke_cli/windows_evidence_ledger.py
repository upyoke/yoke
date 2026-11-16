"""Expected native Windows operations; expectations are never QA verdicts."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from yoke_cli.commands.command_tree import command_routes
from yoke_cli import product_boundary_inventory as boundary

MODES = ("local", "self-hosted-client", "hosted-client")
LEDGER_PATH = Path("docs/verification/windows-ledger")
FIELDS = ("row_id", "operation", "surface", "mode", "expectation", "reason", "issue")
EXPECTATIONS = {"must-pass", "expected-refusal", "not-applicable", "upstream-limitation"}


def row_id(operation: str, surface: str, mode: str) -> str:
    identity = json.dumps([operation, surface, mode], separators=(",", ":"))
    return "windows-" + hashlib.sha256(identity.encode()).hexdigest()[:20]


def expected_rows(repo_root: Path) -> list[dict[str, str]]:
    """Enumerate live commands and manifest-owned hook/desktop promises."""
    inventory = {row.command_helper: row for row in boundary.generate_inventory(repo_root=repo_root)}
    operations = [("yoke " + " ".join(route), "cli", "must-pass", "") for route in command_routes()]
    for manifest_path in sorted((repo_root / "runtime/harness").glob("*/manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        surfaces = manifest.get("session_control", {}).get("surfaces", {})
        hooks_path = manifest_path.parent / Path(manifest.get("worktree_hook_enablement", {}).get("config_path", "hooks.json")).name
        hook_events = set()
        if hooks_path.is_file():
            hook_events.update(json.loads(hooks_path.read_text(encoding="utf-8")).get("hooks", {}))
        for surface, capabilities in surfaces.items():
            for event in hook_events | set(capabilities.get("inject_events", [])):
                operations.append((f"hook {event}", surface, "must-pass", ""))
            if "desktop" in surface:
                for behavior in ("create", "message_active", "message_idle", "message_stopped"):
                    promised = capabilities.get(behavior) == "supported"
                    operations.append((
                        f"desktop {behavior}", surface,
                        "must-pass" if promised else "not-applicable",
                        "" if promised else f"manifest declares {behavior}={capabilities.get(behavior, 'none')}",
                    ))
    rows = []
    for operation, surface, expectation, reason in sorted(set(operations)):
        # Boundary inventory owns command enumeration metadata and shell fallbacks.
        disposition = inventory.get(operation)
        if disposition and disposition.disposition == boundary.OPERATOR_DEBUG_PERMANENT:
            expectation, reason = "not-applicable", "operator-only diagnostic outside product operation"
        for mode in MODES:
            rows.append(dict(zip(FIELDS, (
                row_id(operation, surface, mode), operation, surface, mode,
                expectation, reason, "",
            ))))
    return rows


def load_rows(repo_root: Path) -> list[dict[str, str]]:
    rows = []
    for path in sorted((repo_root / LEDGER_PATH).glob("*.csv")):
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != FIELDS:
                raise ValueError(f"windows_ledger_invalid: repair columns in {path}")
            for row in reader:
                if set(row) != set(FIELDS) or any(value is None for value in row.values()):
                    raise ValueError(f"windows_ledger_invalid: repair row columns in {path}")
                rows.append(row)
    return rows


def validate_rows(rows: list[dict[str, str]], expected: list[dict[str, str]]) -> None:
    ids = [row["row_id"] for row in rows]
    wanted = {row["row_id"] for row in expected}
    missing, obsolete = wanted - set(ids), set(ids) - wanted
    if missing or obsolete or len(ids) != len(set(ids)):
        raise ValueError(
            f"windows_ledger_drift: {len(missing)} missing, {len(obsolete)} obsolete; "
            "refresh the ledger, review expectations and commit its rows"
        )
    for row in rows:
        if row["row_id"] != row_id(row["operation"], row["surface"], row["mode"]):
            raise ValueError("windows_ledger_invalid: row identity changed; refresh the ledger")
        expectation = row["expectation"]
        if expectation not in EXPECTATIONS or (expectation != "must-pass" and not row["reason"].strip()):
            raise ValueError(f"windows_ledger_invalid: repair expectation/reason for {row['row_id']}")
        if expectation == "upstream-limitation":
            issue = urlparse(row["issue"])
            cursor_issue = issue.hostname == "forum.cursor.com" or (
                issue.hostname == "github.com" and issue.path.startswith("/getcursor/cursor/issues/")
            )
            if issue.scheme != "https" or not cursor_issue:
                raise ValueError(f"windows_ledger_invalid: add Cursor issue link for {row['row_id']}")
