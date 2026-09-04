"""One row per CI run a session stopped waiting on.

A worker that dispatches a CI run and then ends its turn has nothing left
in the process to read the conclusion: the watcher it was streaming dies
with the turn. The run still concludes minutes later, and until this table
existed nothing anywhere knew a session was owed that verdict — two
workers sat idle for twenty minutes past their own green runs, and a
person had to notice and message them by hand.

So the moment a gate dispatches a run it records the tuple here, and
:mod:`yoke_core.domain.session_ci_wait_observer` reads the conclusion on
the control-plane cadence and pushes it back. The shape mirrors the
merge-queue landing marker: pending until a sweep observes it, then
``notified_at`` once the notice is accepted.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.schema_init_apply import execute_schema_script


#: Which gate dispatched the run. The notice reads differently for each,
#: because continuing from a selection and continuing from a recorded QA
#: verdict are different acts.
CI_WAIT_SELECTION = "selection"
CI_WAIT_QA_CASE = "qa_case"
CI_WAIT_KINDS = (CI_WAIT_SELECTION, CI_WAIT_QA_CASE)

_KIND_SQL = ",".join(f"'{kind}'" for kind in CI_WAIT_KINDS)

SESSION_CI_RUN_WAITS_CREATE_SQL = f"""
CREATE TABLE IF NOT EXISTS session_ci_run_waits (
  id INTEGER PRIMARY KEY,
  session_id TEXT NOT NULL,
  project_id INTEGER NOT NULL REFERENCES projects(id),
  repo TEXT NOT NULL,
  run_id TEXT NOT NULL,
  head_sha TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL CHECK(kind IN ({_KIND_SQL})),
  continue_command TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  read_at TEXT,
  conclusion TEXT NOT NULL DEFAULT '',
  notified_at TEXT,
  UNIQUE(session_id, run_id)
);
CREATE INDEX IF NOT EXISTS idx_session_ci_run_waits_pending
  ON session_ci_run_waits(project_id, notified_at);
"""


def run_url(repo: str, run_id: str) -> str:
    """The page a person opens to read the run this wait names."""
    return f"https://github.com/{repo}/actions/runs/{run_id}"


def ensure_session_ci_wait_schema(conn: Any) -> None:
    """Converge the additive pending-CI-wait table on ``conn``."""
    execute_schema_script(conn, SESSION_CI_RUN_WAITS_CREATE_SQL)


__all__ = [
    "CI_WAIT_KINDS",
    "CI_WAIT_QA_CASE",
    "CI_WAIT_SELECTION",
    "SESSION_CI_RUN_WAITS_CREATE_SQL",
    "ensure_session_ci_wait_schema",
    "run_url",
]
