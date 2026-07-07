"""HC-path-claim-bash-guard: rendered hook chains include the path-claim guard.

Verifies the post-1638 wiring of ``yoke_core.domain.path_claim_bash_guard``
in the PreToolUse@Bash chain. Two layers are checked:

1. Both Claude ``settings.json`` and Codex ``hooks.json`` register a
   ``yoke hook evaluate`` command for the PreToolUse@Bash matcher --
   that is, the rendered hook config delegates the chain to the stable
   Yoke CLI boundary.
2. ``runtime.harness.hook_runner.chain_registry.chain_for("PreToolUse",
   "Bash")`` includes ``yoke_core.domain.path_claim_bash_guard`` -- the
   ordered policy module list the runner actually executes.

When the guard module is present on disk, the HC additionally invokes the
in-process deny smoke through :func:`evaluate_payload` to verify the
out-of-claim and wrong-cwd narratives still pattern-match.

PASS-with-note when the guard module has not yet been authored -- the HC
shifts into a presence-only check until the substrate lands, mirroring the
``hc_path_integrity`` precedent.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List, Sequence

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
)


_HC_NAME = "HC-path-claim-bash-guard"
_HC_DESC = "Path-claim Bash guard wired into rendered hook chains"

_GUARD_MODULE = "yoke_core.domain.path_claim_bash_guard"
_HOOK_CLI_TOKEN = "yoke hook evaluate"
_CLAUDE_SETTINGS = Path("runtime/harness/claude/settings.json")
_CODEX_HOOKS = Path("runtime/harness/codex/hooks.json")


def _root_path(rel: Path) -> Path:
    root = _resolve_repo_root()
    return Path(root) / rel if root else rel


def _bash_pretool_commands(hook_doc: dict) -> List[str]:
    """Return the list of command strings registered for PreToolUse@Bash."""
    pretool = (hook_doc.get("hooks") or {}).get("PreToolUse") or []
    out: List[str] = []
    for entry in pretool:
        if not isinstance(entry, dict):
            continue
        if entry.get("matcher") != "Bash":
            continue
        for hk in entry.get("hooks") or []:
            cmd = hk.get("command") if isinstance(hk, dict) else None
            if cmd:
                out.append(str(cmd))
    return out


def _hook_cli_delegated(commands: Sequence[str]) -> bool:
    """Return True when at least one command delegates to the hook CLI."""
    return any(_HOOK_CLI_TOKEN in cmd for cmd in commands)


def _chain_has_guard() -> bool:
    """Return True when the chain registry lists the guard for PreToolUse@Bash."""
    from runtime.harness.hook_runner.chain_registry import chain_for

    return _GUARD_MODULE in chain_for("PreToolUse", "Bash")


def _guard_module_available() -> bool:
    return importlib.util.find_spec(_GUARD_MODULE) is not None


_OUT_OF_CLAIM_RE = re.compile(r"out[- ]of[- ]claim|outside.*claim|not in claim", re.I)
_WRONG_CWD_RE = re.compile(
    r"wrong[- ]cwd|wrong working tree|cwd.*mismatch|not in.*worktree", re.I
)


def _run_guard_smoke() -> tuple[bool, str]:
    """Run the path-claim guard's deny smoke. Returns (passed, detail)."""
    from yoke_core.domain.path_claim_bash_guard import evaluate_payload

    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        worktree = root / "worktree"
        main_repo = root / "main"
        (worktree / "inside").mkdir(parents=True)
        (main_repo / "inside").mkdir(parents=True)
        target = main_repo / "inside" / "wrong.py"
        target.write_text("x\n", encoding="utf-8")
        claim = {
            "id": 17,
            "item_id": 1,
            "integration_target": "main",
            "state": "active",
            "covered_paths": ("inside",),
            "worktree_path": str(worktree),
        }
        out_of_claim = evaluate_payload(
            {
                "tool_name": "Bash",
                "session_id": "hc",
                "cwd": str(worktree),
                "tool_input": {"command": "rm outside/file.py"},
            },
            claim=claim,
        )
        # Keep the target relative: absolute /tmp paths are scratch by policy,
        # which would bypass the wrong-cwd branch in clean environments.
        wrong_cwd = evaluate_payload(
            {
                "tool_name": "Bash",
                "session_id": "hc",
                "cwd": str(main_repo),
                "tool_input": {"command": "rm inside/wrong.py"},
            },
            claim=claim,
        )
    output = (out_of_claim.narrative or "") + "\n" + (wrong_cwd.narrative or "")
    out_of_claim_ok = bool(_OUT_OF_CLAIM_RE.search(output))
    wrong_cwd_ok = bool(_WRONG_CWD_RE.search(output))
    if not (out_of_claim_ok and wrong_cwd_ok):
        return False, (
            "deny smoke output missed expected narratives "
            f"(out_of_claim={out_of_claim_ok}, wrong_cwd={wrong_cwd_ok})"
        )
    return True, "deny narratives matched (out_of_claim, wrong_cwd)"


def hc_path_claim_bash_guard(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    claude_path = _root_path(_CLAUDE_SETTINGS)
    codex_path = _root_path(_CODEX_HOOKS)

    if not _guard_module_available():
        rec.record(
            _HC_NAME, _HC_DESC, "PASS",
            f"{_GUARD_MODULE} not yet provisioned; presence/smoke checks skipped",
        )
        return

    issues: List[str] = []
    facts: List[str] = []

    for label, p in (("claude", claude_path), ("codex", codex_path)):
        if not p.exists():
            issues.append(f"{label} hook config missing: {p}")
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            issues.append(f"{label} hook config unreadable: {exc}")
            continue
        cmds = _bash_pretool_commands(doc)
        if _hook_cli_delegated(cmds):
            facts.append(
                f"{label}: PreToolUse@Bash delegates to {_HOOK_CLI_TOKEN}",
            )
        else:
            issues.append(
                f"{label}: PreToolUse@Bash does not delegate to {_HOOK_CLI_TOKEN}",
            )

    if _chain_has_guard():
        facts.append(
            f"chain_registry: {_GUARD_MODULE} present in PreToolUse@Bash chain",
        )
    else:
        issues.append(
            f"chain_registry: {_GUARD_MODULE} absent from PreToolUse@Bash chain",
        )

    smoke_ok, smoke_detail = _run_guard_smoke()
    facts.append(f"deny smoke: {smoke_detail}")
    if not smoke_ok:
        issues.append(smoke_detail)

    if issues:
        rec.record(_HC_NAME, _HC_DESC, "FAIL", "\n".join(issues + facts))
    else:
        rec.record(_HC_NAME, _HC_DESC, "PASS", "\n".join(facts))
