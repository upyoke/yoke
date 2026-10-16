"""Select only recorded, unchanged folder trust for one exact checkout."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from yoke_contracts import harness_folder_trust as trust
from yoke_contracts import harness_settings_ledger as ledger
from yoke_contracts.harness_settings_revert import revert_entry
from yoke_contracts.harness_unattended_posture import codex_config_path
from yoke_contracts.codex_config_posture import parse_config


def revert_folder_trust(checkout: Path, *, exclusive_reason: str = "") -> list[dict]:
    """Consume successful exact-entry reverts; retain unresolved ownership evidence.

    Shared approval posture and whole user configuration files are never selected.
    Older created-file records lack content identity and cannot authorize removal.
    """
    root = str(checkout.resolve())
    results = []
    try:
        with ledger.mutation() as entries:
            matched = set()
            for entry in list(entries):
                scope = _scope(entry)
                if scope is None:
                    continue
                owner, family = scope
                if Path(owner).expanduser().resolve() != checkout.resolve():
                    continue
                matched.add(
                    (family, str(Path(entry["file"]).expanduser().resolve()), owner)
                )
                if exclusive_reason:
                    results.append(_result(family, "preserved", exclusive_reason, root))
                    continue
                try:
                    if entry["kind"] == "created_file" and Path(entry["file"]).exists():
                        target = Path(entry["file"])
                        if (
                            not entry.get("sha256")
                            or hashlib.sha256(target.read_bytes()).hexdigest()
                            != entry["sha256"]
                        ):
                            results.append(
                                _result(
                                    family,
                                    "preserved",
                                    "trust_modified_or_unproven",
                                    root,
                                )
                            )
                            continue
                    line = revert_entry(entry)
                    if line.startswith("left your setting in place:"):
                        results.append(
                            _result(family, "preserved", "trust_modified", root)
                        )
                    else:
                        entries.remove(entry)
                        results.append(
                            _result(
                                family,
                                "removed" if line else "absent",
                                "owned_exact_entry",
                                root,
                            )
                        )
                except (OSError, ValueError, KeyError, TypeError) as exc:
                    results.append(
                        _result(family, "failed", "trust_unreadable", root, str(exc))
                    )
            for family, owner, target in _current(root):
                if Path(owner).expanduser().resolve() != checkout.resolve():
                    results.append(_result(family, "preserved", "broader_trust", owner))
                elif (family, str(target.expanduser().resolve()), owner) not in matched:
                    results.append(
                        _result(family, "preserved", "trust_ownership_unknown", root)
                    )
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        results.append(
            _result("ledger", "failed", "trust_ledger_unreadable", root, str(exc))
        )
    return results


def _scope(entry: dict) -> tuple[str, str] | None:
    kind = entry.get("kind")
    if kind == "codex_trust" and isinstance(entry.get("trust_key"), str):
        return entry["trust_key"], "codex"
    keys = entry.get("keys")
    if (
        kind == "json"
        and isinstance(keys, list)
        and len(keys) == 3
        and keys[0] == trust.CLAUDE_PROJECTS_KEY
        and keys[2] == trust.CLAUDE_TRUST_KEY
    ):
        return keys[1], "claude-code"
    if kind == "created_file":
        target = Path(entry.get("file", ""))
        if target.name != trust.CURSOR_TRUST_FILENAME:
            return None
        # Missing old files need no mutation; their path alone cannot prove a scope.
        if target.is_file():
            payload = json.loads(target.read_text(encoding="utf-8"))
            owner = payload.get("workspacePath") if isinstance(payload, dict) else None
            if isinstance(owner, str):
                return owner, "cursor"
    return None


def _current(root: str):
    """Detect unowned exact and broader entries without rewriting user state."""
    targets = {
        "claude-code": trust.claude_state_path(),
        "codex": codex_config_path(),
        "cursor": trust.cursor_trust_file(root),
    }
    for family, target in targets.items():
        if not target.is_file():
            continue
        text = target.read_text(encoding="utf-8")
        if family == "cursor":
            yield family, root, target
            continue
        payload = parse_config(text) if family == "codex" else json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError(
                f"{target}: configuration is not an object; repair it and retry"
            )
        projects = payload.get("projects") or {}
        if not isinstance(projects, dict):
            raise ValueError(
                f"{target}: projects is not an object; repair the harness config and retry"
            )
        for owner in projects:
            if Path(owner).is_absolute() and Path(root).is_relative_to(
                Path(owner).resolve()
            ):
                yield family, owner, target
    for parent in Path(root).parents:
        if trust.cursor_trust_file(parent).is_file():
            yield "cursor", str(parent), trust.cursor_trust_file(parent)


def _result(
    family: str, status: str, reason: str, checkout: str, detail: str = ""
) -> dict:
    return {
        "harness": family,
        "status": status,
        "reason": reason,
        "checkout": checkout,
        "detail": detail,
        "recovery": "Review the preserved entry in the named harness configuration; resolve ownership or sharing and rerun project uninstall. Never use machine uninstall to resolve project cleanup.",
    }
