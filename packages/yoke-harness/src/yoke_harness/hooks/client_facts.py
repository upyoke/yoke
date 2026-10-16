"""Collect the client facts a hook chain's server-run policies read.

Every evaluation path calls :func:`collect_client_facts` with the chain it
is about to run: the HTTPS relay ships the result in ``payload_extra``, and
an in-process evaluation merges it into the payload it runs. The facts each
policy needs are declared once in
:mod:`yoke_contracts.hook_runner.policy_home`; this module only observes
them on the machine running the harness.

A collector that raises does not fail the hook: the fact is left out, so the
reading policy applies its documented no-fact behaviour, and the failure is
written to stderr as ``YOKE_CLIENT_FACT_FAILED`` naming the fact and error.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping

from yoke_contracts.fleet_watcher_observation import (
    FLEET_WATCHER_OBSERVATION_KEY,
    observe_fleet_watcher,
)
from yoke_contracts.hook_runner import client_facts as cf
from yoke_contracts.hook_runner import lint_policy
from yoke_contracts.hook_runner.chain_registry import chain_for
from yoke_contracts.hook_runner.guard_scope import applicable_chain
from yoke_contracts.hook_runner.main_commit import CLIENT_GIT_COMMIT_FACTS_KEY
from yoke_contracts.hook_runner.policy_home import client_facts_for
from yoke_contracts.hook_runner.project_scope import HookProjectScope
from yoke_contracts.hook_runner.session_cwd import (
    CLIENT_CLAUDE_JOB_TMP_KEY,
    CLIENT_MACHINE_HOME_KEY,
    CLIENT_SCRATCH_ROOT_KEY,
    client_claude_job_tmp_fact,
    client_machine_home_fact,
    client_scratch_root_fact,
)
from yoke_contracts.machine_config import runtime as machine_config
from yoke_contracts.session_control import turn_end_events
from yoke_contracts.session_control.resume import RESUME_ATTEMPT_ENV
from yoke_contracts.turn_end_evidence import PAYLOAD_KEY as TURN_END_EVIDENCE_KEY

from yoke_harness.hooks.client_fact_probes import (
    capture_files_fact,
    main_head_fact,
    yoke_source_root_fact,
)
from yoke_harness.hooks.client_write_targets import write_targets_fact
from yoke_harness.hooks.main_commit_client import collect_git_commit_facts
from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV

FAILURE_MARKER = "YOKE_CLIENT_FACT_FAILED"


@dataclass(frozen=True)
class Observation:
    """What one collector may look at: the event, its payload, the harness."""

    event_name: str
    payload: Mapping[str, object]
    executor: str


def _turn_end_evidence(obs: Observation) -> dict:
    if obs.event_name not in turn_end_events(obs.executor):
        return {}
    from yoke_contracts.turn_end_evidence import (
        extract_turn_end_evidence,
        read_transcript_tail,
    )

    path = obs.payload.get("transcript_path")
    text = read_transcript_tail(path) if isinstance(path, str) and path else None
    evidence = extract_turn_end_evidence(
        payload=dict(obs.payload), transcript_text=text
    )
    return {TURN_END_EVIDENCE_KEY: evidence.as_dict()}


def _headless_launch(obs: Observation) -> dict:
    headless = any(
        str(os.environ.get(name) or "").strip()
        for name in (LAUNCH_CONTEXT_ENV, RESUME_ATTEMPT_ENV)
    )
    return cf.client_fact(cf.HEADLESS_LAUNCH_KEY, headless)


def _machine_settings(obs: Observation) -> dict:
    settings = machine_config.read_settings()
    values = {key: settings[key] for key in cf.FACT_MACHINE_SETTINGS if key in settings}
    return cf.client_fact(cf.MACHINE_SETTINGS_KEY, values)


def lint_config_snapshot(payload: Mapping[str, object]) -> dict:
    """Snapshot the lint-config of the checkout the hook runs in."""
    cwd = payload.get("cwd")
    try:
        return lint_policy.snapshot_from_workspace(
            start=cwd if isinstance(cwd, str) and cwd else None
        )
    except Exception:
        return {}


_COLLECTORS: dict[str, Callable[[Observation], dict]] = {
    CLIENT_GIT_COMMIT_FACTS_KEY: lambda obs: collect_git_commit_facts(
        dict(obs.payload)
    ),
    CLIENT_MACHINE_HOME_KEY: lambda obs: client_machine_home_fact(
        str(Path.home().resolve())
    ),
    CLIENT_SCRATCH_ROOT_KEY: lambda obs: client_scratch_root_fact(
        machine_config.effective_temp_root()
    ),
    CLIENT_CLAUDE_JOB_TMP_KEY: lambda obs: client_claude_job_tmp_fact(
        os.environ.get("CLAUDE_JOB_DIR", "")
    ),
    FLEET_WATCHER_OBSERVATION_KEY: lambda obs: observe_fleet_watcher(
        dict(obs.payload), executor=obs.executor, event_name=obs.event_name
    ),
    TURN_END_EVIDENCE_KEY: _turn_end_evidence,
    cf.HEADLESS_LAUNCH_KEY: _headless_launch,
    cf.MACHINE_SETTINGS_KEY: _machine_settings,
    cf.SOURCE_ROOT_KEY: lambda obs: yoke_source_root_fact(),
    cf.MAIN_HEAD_KEY: lambda obs: main_head_fact(obs.payload),
    cf.CAPTURE_FILES_KEY: lambda obs: capture_files_fact(obs.payload),
    cf.WRITE_TARGETS_KEY: lambda obs: write_targets_fact(obs.payload),
}


def tool_matcher(event_name: str, payload: Mapping[str, object]) -> str | None:
    """Return the chain matcher (tool name) for one hook event."""
    if event_name in {"PreToolUse", "PostToolUse"}:
        tool_name = payload.get("tool_name")
        return tool_name if isinstance(tool_name, str) and tool_name else None
    if event_name == "apply_patch":
        return "apply_patch"
    return None


def event_chain(
    event_name: str,
    payload: Mapping[str, object],
    project_scope: HookProjectScope | None = None,
) -> list[str]:
    """Return the chain this event runs, narrowed to the project scope.

    An unresolvable *project_scope* raises its own named refusal.
    """
    chain = chain_for(event_name, tool_matcher(event_name, payload))
    if project_scope is not None:
        chain = applicable_chain(chain, project_scope.require_project_id())
    return chain


def collect_client_facts(
    event_name: str,
    payload: Mapping[str, object],
    executor: str,
    chain: Iterable[str],
) -> dict[str, object]:
    """Observe every fact the server-run policies of *chain* read."""
    obs = Observation(event_name, payload, executor)
    # Every chain policy's mode resolves through the session checkout's
    # lint-config, so its snapshot rides with every chain (empty when the
    # checkout has none) and the authority never reads its own.
    facts: dict[str, object] = {
        lint_policy.SNAPSHOT_PAYLOAD_KEY: lint_config_snapshot(payload)
    }
    for key in sorted(client_facts_for(chain)):
        try:
            facts.update(_COLLECTORS[key](obs))
        except Exception as exc:  # a missing fact must not fail the hook
            sys.stderr.write(
                f"WARNING: {FAILURE_MARKER}: {key}: {type(exc).__name__}: {exc}; "
                "the policies reading it apply their no-fact behaviour\n"
            )
    return facts


__all__ = [
    "FAILURE_MARKER",
    "Observation",
    "collect_client_facts",
    "event_chain",
    "lint_config_snapshot",
    "tool_matcher",
]
