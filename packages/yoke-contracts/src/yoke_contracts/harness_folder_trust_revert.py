"""Select only recorded, unchanged folder trust for one exact checkout."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from yoke_contracts import harness_folder_trust as trust
from yoke_contracts import harness_settings_ledger as ledger
from yoke_contracts.harness_settings_revert import revert_entry
from yoke_contracts.harness_unattended_posture import (
    CODEX_TRUST_LEVEL,
    CODEX_TRUST_LEVEL_KEY,
    codex_config_path,
)
from yoke_contracts.codex_config_posture import parse_config
from yoke_contracts.codex_hook_trust_store import hooks_file_for
from yoke_contracts.codex_hook_trust_toml import (
    CodexHookTrustStoreError,
    all_hook_entries,
    filter_tables,
    hook_path,
    mutate,
)


def revert_folder_trust(
    checkout: Path, *, exclusive_reason: str = "", lanes_dir: Path | None = None
) -> list[dict]:
    """Consume successful exact-entry reverts; retain unresolved ownership evidence.

    Entries owned by the checkout or by a lane under ``lanes_dir`` are selected,
    plus the Codex hook trust install minted for the checkout's hooks file and
    lane provisioning mirrored onto its lanes. Shared approval posture
    and whole user configuration files are never selected. Older created-file
    records lack content identity and cannot authorize removal.
    """
    root = str(checkout.resolve())
    lanes = lanes_dir.expanduser().resolve() if lanes_dir is not None else None
    results = []
    try:
        with ledger.mutation() as entries:
            matched = set()
            for entry in list(entries):
                scope = _scope(entry)
                if scope is None:
                    continue
                owner, family = scope
                owner_path = Path(owner).expanduser().resolve()
                if owner_path != checkout.resolve() and not (
                    lanes is not None and owner_path.is_relative_to(lanes)
                ):
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
                if (family, str(target.expanduser().resolve()), owner) not in matched:
                    results.append(
                        _result(family, "preserved", "trust_ownership_unknown", root)
                    )
    except (OSError, ValueError, TypeError, RuntimeError) as exc:
        results.append(
            _result("ledger", "failed", "trust_ledger_unreadable", root, str(exc))
        )
    if not exclusive_reason:
        results.extend(_revert_codex_hook_trust(checkout, lanes_dir, root))
    return results


def _revert_codex_hook_trust(
    checkout: Path, lanes_dir: Path | None, root: str
) -> list[dict]:
    """Remove the Codex hook trust Yoke wrote for this checkout and its lanes.

    Install mints trust for the checkout's own Yoke-authored hooks file, and
    lane provisioning mirrors it onto each lane; neither writes a ledger entry.
    The checkout's hooks path and a hooks path under its lanes directory are
    the ownership proof. Codex keys literal paths, so both the stated and the
    resolved spelling match.
    """
    config = codex_config_path()
    if not config.is_file():
        return []
    stated = checkout.expanduser()
    exact = {str(hooks_file_for(stated)), str(hooks_file_for(stated.resolve()))}
    prefixes: tuple[str, ...] = ()
    if lanes_dir is not None:
        lanes = lanes_dir.expanduser()
        prefixes = (f"{lanes}/", f"{lanes.resolve()}/")

    def owned(path: str) -> bool:
        return path in exact or (bool(prefixes) and path.startswith(prefixes))

    def plan(text: str, document: dict) -> tuple[str, int]:
        keys = {
            key
            for key in all_hook_entries(document)
            if owned(hook_path(key) or "")
        }
        updated, count, _ = filter_tables(text, keys, set())
        if count != len(keys):
            raise CodexHookTrustStoreError(
                "checkout hook trust uses an unsupported inline TOML layout"
            )
        return updated, count

    try:
        removed = mutate(config, plan)
    except CodexHookTrustStoreError as exc:
        return [_result("codex", "failed", "hook_trust_unreadable", root, str(exc))]
    return [_result("codex", "removed", "owned_hook_trust", root)] if removed else []


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
    """Detect unowned trust for this exact checkout without rewriting user state.

    Harnesses keep metadata for folders they have only seen; an entry counts
    only when it carries the trust value the grant side writes. Parent-folder
    trust is never Yoke's: install grants only the exact checkout.
    """
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
        for owner, entry in projects.items():
            if (
                _grants_trust(family, entry)
                and Path(owner).is_absolute()
                and Path(owner).resolve() == Path(root)
            ):
                yield family, owner, target


def _grants_trust(family: str, entry: object) -> bool:
    if not isinstance(entry, dict):
        return False
    if family == "codex":
        return entry.get(CODEX_TRUST_LEVEL_KEY) == CODEX_TRUST_LEVEL
    return entry.get(trust.CLAUDE_TRUST_KEY) is True


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
