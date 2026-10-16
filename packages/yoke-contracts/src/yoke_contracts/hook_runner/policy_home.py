"""Where each hook chain policy evaluates: the one home for every policy.

Yoke evaluates one hook chain in three modes: in-process on a local-universe
machine, and split across the HTTPS relay for self-hosted and hosted
installs, where the chain runs on the control-plane authority. The authority
cannot see the client machine — its files, git state, processes,
environment, captures or transcripts — so every chain policy declares one
home here, and both sides of the relay read this table:

- ``CLIENT`` — the verdict needs the client machine and no control-plane
  state. The relay client evaluates it before posting
  (``yoke_harness.hooks.local_subset``); the authority skips it and records
  the module id in the response's ``degraded`` list ("delegated to the
  client", not "protection off").
- ``SERVER`` — the verdict needs only the hook payload and control-plane
  state, so it runs wherever the chain runs.
- ``SERVER_WITH_CLIENT_FACTS`` — the verdict needs control-plane state and
  named client observations. The client collects exactly those facts
  (:mod:`yoke_contracts.hook_runner.client_facts`) on every evaluation path
  and the policy reads only the facts, never its own machine.

``tests/hook_policy_homes/`` checks this table against the chains and both
relay halves, and scans every function a server-run policy can reach: an
unclassified local read fails until its policy moves home, names the client
fact it needs, or carries a written reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Iterable, Mapping

from yoke_contracts.fleet_watcher_observation import FLEET_WATCHER_OBSERVATION_KEY
from yoke_contracts.hook_runner.client_facts import (
    CAPTURE_FILES_KEY,
    HEADLESS_LAUNCH_KEY,
    MACHINE_SETTINGS_KEY,
    MAIN_HEAD_KEY,
    SOURCE_ROOT_KEY,
    WRITE_TARGETS_KEY,
)
from yoke_contracts.hook_runner.main_commit import CLIENT_GIT_COMMIT_FACTS_KEY
from yoke_contracts.hook_runner.session_cwd import (
    CLIENT_CLAUDE_JOB_TMP_KEY,
    CLIENT_MACHINE_HOME_KEY,
    CLIENT_SCRATCH_ROOT_KEY,
)
from yoke_contracts.turn_end_evidence import PAYLOAD_KEY as TURN_END_EVIDENCE_KEY


class PolicyHome(str, Enum):
    CLIENT = "client"
    SERVER = "server"
    SERVER_WITH_CLIENT_FACTS = "server_with_client_facts"


@dataclass(frozen=True)
class PolicyPlacement:
    """One policy's home and, for a fact-fed server policy, its facts."""

    home: PolicyHome
    client_facts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        needs_facts = self.home is PolicyHome.SERVER_WITH_CLIENT_FACTS
        if needs_facts != bool(self.client_facts):
            raise ValueError(
                "client_facts are required for, and only for, "
                f"{PolicyHome.SERVER_WITH_CLIENT_FACTS.value}"
            )


_CLIENT = PolicyPlacement(PolicyHome.CLIENT)
_SERVER = PolicyPlacement(PolicyHome.SERVER)


def _facts(*keys: str) -> PolicyPlacement:
    return PolicyPlacement(PolicyHome.SERVER_WITH_CLIENT_FACTS, tuple(keys))


_D = "yoke_core.domain."
_H = "yoke_core.hooks."

_POLICY_HOMES: dict[str, PolicyPlacement] = {
    # Client: each reads the client's checkout, git state or home directly.
    _D + "db_error_hook": _CLIENT,  # stray-DB scan of the client repo root
    _D + "hint_file_line_limit_approach": _CLIENT,  # counts target file lines
    _D + "lint_destructive_git": _CLIENT,  # git status / stash inspection
    _D + "lint_local_privacy": _CLIENT,  # the client's home and cwd
    _D + "lint_python_runtime_import_in_tmp": _CLIENT,  # walks target parents
    _D + "lint_shell_backtick_search": _CLIENT,  # machine guard, no project
    _D + "lint_unmatched_path_glob": _CLIENT,  # expands globs on client FS
    # Lifecycle side effects on the client's checkout and env file. The
    # authority's identity and cleanup halves run as relay ensure-register
    # and ``yoke_core.hooks.remote_lifecycle``.
    _H + "session_dispatch": _CLIENT,
    # Server with named client facts.
    _D + "hint_monitor_relay": _facts(MACHINE_SETTINGS_KEY),
    _D + "lint_headless_watcher_timeout": _facts(HEADLESS_LAUNCH_KEY),
    _D + "lint_lane_main_write": _facts(WRITE_TARGETS_KEY, CLIENT_MACHINE_HOME_KEY),
    _D + "lint_long_command_polling": _facts(CAPTURE_FILES_KEY),
    _D + "lint_main_commit": _facts(CLIENT_GIT_COMMIT_FACTS_KEY),
    _D + "lint_session_cwd": _facts(
        CLIENT_MACHINE_HOME_KEY,
        CLIENT_SCRATCH_ROOT_KEY,
        CLIENT_CLAUDE_JOB_TMP_KEY,
        SOURCE_ROOT_KEY,
        MACHINE_SETTINGS_KEY,
    ),
    _D + "observe_pre": _facts(MAIN_HEAD_KEY),
    _D + "path_claim_bash_guard": _facts(
        CLIENT_SCRATCH_ROOT_KEY, CLIENT_MACHINE_HOME_KEY
    ),
    _D + "turn_end_promised_work_gate": _facts(TURN_END_EVIDENCE_KEY),
    _H + "session_message_delivery": _facts(FLEET_WATCHER_OBSERVATION_KEY),
    # Server: payload text plus control-plane state only.
    _D + "lint_claim_ownership_mutations": _SERVER,
    _D + "lint_db_cmd": _SERVER,
    _D + "lint_event_registry": _SERVER,
    _D + "lint_git_stash_arg_order": _SERVER,
    _D + "lint_if_status_capture": _SERVER,
    _D + "lint_monitor_watcher_tail": _SERVER,
    _D + "lint_no_agent_curl_against_yoke_api": _SERVER,
    _D + "lint_no_agent_runtime_api_import_from_c": _SERVER,
    _D + "lint_no_agent_session_end": _SERVER,
    _D + "lint_pipe_to_truncator": _SERVER,
    _D + "lint_raw_pytest_full_suite": _SERVER,
    _D + "lint_shell_quoted_function_payload": _SERVER,
    _D + "lint_structured_field_transform_shell": _SERVER,
    _D + "lint_subagent_background": _SERVER,
    _D + "lint_subagent_fleet_messaging": _SERVER,
    _D + "lint_tc_label": _SERVER,
    _D + "lint_watcher_module_form": _SERVER,
    _D + "lint_workspace_cwd_match": _SERVER,
    _D + "lint_write_path": _SERVER,
    _D + "lint_yoke_adapter_stderr_visibility": _SERVER,
    _D + "lint_yoke_quoted_shell_substitution": _SERVER,
    _D + "observe": _SERVER,
    _D + "path_claim_pre_edit_guard": _SERVER,
    _D + "reflection_capture_hook": _SERVER,
    _H + "heartbeat": _SERVER,
    _H + "session_broker_wake": _SERVER,
    _H + "session_launch_attestation": _SERVER,
    _H + "session_resume_block": _SERVER,
}

POLICY_HOMES: Mapping[str, PolicyPlacement] = MappingProxyType(_POLICY_HOMES)

CLIENT_POLICIES: frozenset[str] = frozenset(
    module for module, p in _POLICY_HOMES.items() if p.home is PolicyHome.CLIENT
)


def placement(module_id: str) -> PolicyPlacement:
    """Return *module_id*'s placement; an unclassified chain module raises."""
    try:
        return POLICY_HOMES[module_id]
    except KeyError:
        raise KeyError(
            f"hook policy {module_id} has no home; classify it in "
            "yoke_contracts.hook_runner.policy_home"
        ) from None


def client_facts_for(chain: Iterable[str]) -> frozenset[str]:
    """Return every client fact key the server-run policies of *chain* read."""
    return frozenset(key for module in chain for key in placement(module).client_facts)


__all__ = [
    "CLIENT_POLICIES",
    "POLICY_HOMES",
    "PolicyHome",
    "PolicyPlacement",
    "client_facts_for",
    "placement",
]
