"""Named facts only the machine running the harness can observe.

A hook chain policy that runs on the control-plane authority cannot see the
client machine: its files, git state, processes, environment, captures or
transcripts. When such a policy needs one of those answers, the client
observes it and ships it as a named fact in the hook payload. Every
evaluation path collects the same facts the same way — the HTTPS relay sends
them in ``payload_extra``, and an in-process local evaluation merges them
into the payload it runs — so a policy reads only the fact and behaves the
same in every mode.

Each fact rides under its own payload key wrapped in a schema envelope::

    {"_yoke_client_<name>": {"schema": 1, "value": <json value>}}

A missing or malformed fact reads as ``None``. The reader never substitutes
its own machine's answer: the evaluating side states what it does without
the fact (allow, or the documented default) instead.

Facts that predate this envelope keep their own shapes and keys:
:data:`~yoke_contracts.hook_runner.main_commit.CLIENT_GIT_COMMIT_FACTS_KEY`,
the three roots in :mod:`yoke_contracts.hook_runner.session_cwd`,
:data:`~yoke_contracts.fleet_watcher_observation.FLEET_WATCHER_OBSERVATION_KEY`
and :data:`~yoke_contracts.turn_end_evidence.PAYLOAD_KEY`.
"""

from __future__ import annotations

from typing import Any, Mapping

FACT_SCHEMA = 1

#: Whether the session runs under a relay launch or resume (headless).
HEADLESS_LAUNCH_KEY = "_yoke_client_headless_launch"
#: Scratch roots plus the state of each capture file a command names.
CAPTURE_FILES_KEY = "_yoke_client_capture_files"
#: Resolved form, ignore status and live lanes for each path a payload names.
WRITE_TARGETS_KEY = "_yoke_client_write_targets"
#: Machine-local settings (``~/.yoke/config.json``) a policy reads.
MACHINE_SETTINGS_KEY = "_yoke_client_machine_settings"
#: The Yoke source checkout this client's installed code runs from.
SOURCE_ROOT_KEY = "_yoke_client_yoke_source_root"
#: Recent commits on the session checkout's ``main`` branch.
MAIN_HEAD_KEY = "_yoke_client_main_head"

#: Machine settings keys the chain reads through ``MACHINE_SETTINGS_KEY``.
SESSION_CWD_STATUS_MODE_SETTING = "lint_session_cwd_status_mode"
MONITOR_RELAY_REMINDER_SETTING = "monitor_relay_hint_text"
FACT_MACHINE_SETTINGS: tuple[str, ...] = (
    SESSION_CWD_STATUS_MODE_SETTING,
    MONITOR_RELAY_REMINDER_SETTING,
)

#: Commits of ``main`` history the client ships for drift detection.
MAIN_HEAD_HISTORY = 20


def client_fact(key: str, value: Any) -> dict[str, Any]:
    """Wrap one observed *value* for the payload under *key*."""
    return {key: {"schema": FACT_SCHEMA, "value": value}}


def read_client_fact(payload: Mapping[str, Any], key: str) -> Any:
    """Return the fact value under *key*, or ``None`` when absent/invalid."""
    raw = payload.get(key) if isinstance(payload, Mapping) else None
    if not isinstance(raw, Mapping) or raw.get("schema") != FACT_SCHEMA:
        return None
    return raw.get("value")


def headless_launch(payload: Mapping[str, Any]) -> bool:
    """True only when the client reported a relay launch or resume."""
    return read_client_fact(payload, HEADLESS_LAUNCH_KEY) is True


def machine_setting(payload: Mapping[str, Any], key: str) -> str:
    """Return the client's value for one machine setting, or ``""``."""
    values = read_client_fact(payload, MACHINE_SETTINGS_KEY)
    if not isinstance(values, Mapping):
        return ""
    value = values.get(key)
    return value.strip() if isinstance(value, str) else ""


def yoke_source_root(payload: Mapping[str, Any]) -> str:
    """Return the client's Yoke source checkout root, or ``""``."""
    value = read_client_fact(payload, SOURCE_ROOT_KEY)
    return value if isinstance(value, str) and value.startswith("/") else ""


def capture_roots(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the client's scratch roots a capture path may live under."""
    fact = read_client_fact(payload, CAPTURE_FILES_KEY)
    roots = fact.get("roots") if isinstance(fact, Mapping) else None
    if not isinstance(roots, list):
        return ()
    return tuple(r for r in roots if isinstance(r, str) and r.startswith("/"))


def capture_file_state(
    payload: Mapping[str, Any], path: str
) -> Mapping[str, Any] | None:
    """Return ``{"completed": bool, "age_seconds": float|None}`` for *path*."""
    fact = read_client_fact(payload, CAPTURE_FILES_KEY)
    files = fact.get("files") if isinstance(fact, Mapping) else None
    state = files.get(path) if isinstance(files, Mapping) else None
    return state if isinstance(state, Mapping) else None


def write_target(payload: Mapping[str, Any], raw: str) -> Mapping[str, Any] | None:
    """Return ``{"path": str, "ignored": bool|None}`` for one raw operand."""
    fact = read_client_fact(payload, WRITE_TARGETS_KEY)
    paths = fact.get("paths") if isinstance(fact, Mapping) else None
    entry = paths.get(raw) if isinstance(paths, Mapping) else None
    return entry if isinstance(entry, Mapping) else None


def live_worktrees(payload: Mapping[str, Any]) -> frozenset[str] | None:
    """Return worktree directories present on the client, or ``None``."""
    fact = read_client_fact(payload, WRITE_TARGETS_KEY)
    lanes = fact.get("worktrees") if isinstance(fact, Mapping) else None
    if not isinstance(lanes, list):
        return None
    return frozenset(p for p in lanes if isinstance(p, str))


def main_head(payload: Mapping[str, Any]) -> list[tuple[str, str]] | None:
    """Return the client's newest ``main`` commits as ``(sha, subject)``."""
    fact = read_client_fact(payload, MAIN_HEAD_KEY)
    commits = fact.get("commits") if isinstance(fact, Mapping) else None
    if not isinstance(commits, list):
        return None
    pairs = [
        (c[0], c[1])
        for c in commits
        if isinstance(c, list) and len(c) == 2 and all(isinstance(v, str) for v in c)
    ]
    return pairs or None


__all__ = [
    "CAPTURE_FILES_KEY",
    "FACT_MACHINE_SETTINGS",
    "FACT_SCHEMA",
    "HEADLESS_LAUNCH_KEY",
    "MACHINE_SETTINGS_KEY",
    "MAIN_HEAD_HISTORY",
    "MAIN_HEAD_KEY",
    "MONITOR_RELAY_REMINDER_SETTING",
    "SESSION_CWD_STATUS_MODE_SETTING",
    "SOURCE_ROOT_KEY",
    "WRITE_TARGETS_KEY",
    "capture_file_state",
    "capture_roots",
    "client_fact",
    "headless_launch",
    "live_worktrees",
    "machine_setting",
    "main_head",
    "read_client_fact",
    "write_target",
    "yoke_source_root",
]
