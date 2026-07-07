"""Agent and harness health checks — agent prompt consistency, canonical
adapter drift, and browser substrate.

This module owns three HCs (agent_consistency, agent_canonical_drift,
browser_substrate) directly and re-exports the rest of the agent/harness
HC family from sibling modules so ``doctor.py``'s import block stays a
single ``from yoke_core.engines.doctor_hc_agents import (...)``.

HC functions owned here: HC-agent-consistency, HC-agent-canonical-drift,
HC-browser-substrate.

Sibling modules (re-exported for ``doctor.py``):
- ``doctor_hc_agents_hooks`` — hook executability, self-test,
  session-startup hook (also owns the shared hook-command parsing
  helpers used by ``hc_agent_consistency``).
- ``doctor_hc_agents_prompts`` — prompt-command and prompt-doctrine
  consistency.
- ``doctor_hc_agents_sessions`` — stale session files and reclaimer
  liveness.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import yoke_core.engines.doctor_report as _base

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
)

from yoke_core.engines.doctor_hc_agents_hooks import (  # noqa: F401
    _classify_hook_command,
    _extract_hook_command,
    _hook_command_exists,
    _python_module_exists,
    hc_hook_executability,
    hc_self_test,
    hc_session_startup_hook,
)
from yoke_core.engines.doctor_hc_agents_prompts import (  # noqa: F401
    hc_prompt_command_consistency,
    hc_prompt_doctrine_consistency,
)
from yoke_core.engines.doctor_hc_agents_sessions import (  # noqa: F401
    hc_stale_reclaim_collision,
    hc_stale_session_reclaimer_alive,
    hc_stale_sessions,
)


def hc_agent_consistency(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-agent-consistency: Agent prompt consistency — hook references exist."""
    repo_root = _base._resolve_repo_root()
    if not repo_root:
        rec.record("HC-agent-consistency", "Agent prompt consistency", "PASS", "")
        return

    issues: List[str] = []
    agents_dir = Path(repo_root) / ".claude" / "agents"
    if not agents_dir.is_dir():
        rec.record("HC-agent-consistency", "Agent prompt consistency", "PASS", "")
        return

    for agent in sorted(agents_dir.glob("yoke-*.md")):
        agent_name = agent.stem
        in_fm = False
        for line in agent.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip() == "---":
                if not in_fm:
                    in_fm = True
                else:
                    break
            if "command:" in line:
                command = _extract_hook_command(line)
                kind, target = _classify_hook_command(command)
                if kind in {"", "shell-literal", "python-exec"}:
                    continue
                if kind == "python-module":
                    if not _python_module_exists(target, repo_root):
                        issues.append(
                            f"- {agent_name}: hook references python module {target} which does not exist"
                        )
                    continue
                cmd_path = target
                if not _hook_command_exists(cmd_path, repo_root):
                    issues.append(f"- {agent_name}: hook references {cmd_path} which does not exist")

    if issues:
        rec.record("HC-agent-consistency", "Agent prompt consistency", "FAIL", "\n".join(issues))
    else:
        rec.record("HC-agent-consistency", "Agent prompt consistency", "PASS", "")


def hc_agent_canonical_drift(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-agent-canonical-drift: Claude adapters match canonical sources."""
    from yoke_core.domain.agents_render import detect_drift
    repo_root = _base._resolve_repo_root()
    kwargs = {"target_root": Path(repo_root)} if repo_root else {}
    try:
        try:
            drift = detect_drift(**kwargs)
        except TypeError:
            drift = detect_drift()
    except Exception as exc:
        rec.record("HC-agent-canonical-drift", "Claude adapter canonical drift", "FAIL",
                   f"drift detection failed: {exc}")
        return
    if drift:
        rec.record("HC-agent-canonical-drift", "Claude adapter canonical drift", "FAIL",
                   "\n".join(f"- {entry}" for entry in drift))
    else:
        rec.record("HC-agent-canonical-drift", "Claude adapter canonical drift", "PASS", "")


def hc_browser_substrate(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-browser-substrate: machine-level browser runtime health."""
    from yoke_core.domain import browser_runtime_home

    browser_dir = browser_runtime_home.runtime_dir()
    if not browser_dir.is_dir():
        rec.record("HC-browser-substrate", "Browser substrate health", "WARN",
                    f"browser runtime not materialized at {browser_dir} — "
                    "`python3 -m yoke_core.domain.browser_client daemon start` provisions it")
        return

    issues: List[str] = []
    if not (browser_dir / "package.json").is_file():
        issues.append(f"- package.json not found in {browser_dir}")
    if not (browser_dir / "node_modules").is_dir():
        issues.append(f"- node_modules not installed — run: npm install (in {browser_dir}); "
                      "daemon start auto-installs")

    if issues:
        rec.record("HC-browser-substrate", "Browser substrate health", "WARN", "\n".join(issues))
    else:
        # Check for Chromium binary
        r = _base._run(
            ["node", "-e",
             "const {chromium} = require('playwright'); "
             "console.log(chromium.executablePath())"],
            timeout=10, cwd=str(browser_dir),
        )
        if r.returncode == 0 and r.stdout.strip() and Path(r.stdout.strip()).is_file():
            rec.record("HC-browser-substrate", "Browser substrate health", "PASS", "")
        else:
            rec.record("HC-browser-substrate", "Browser substrate health", "WARN",
                        f"Chromium binary not found — run: npx playwright install chromium (in {browser_dir})")
