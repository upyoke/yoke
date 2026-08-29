"""Static configuration for the update-status subprocess test environment."""

from __future__ import annotations

import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / ".agents" / "skills" / "yoke" / "scripts"
TEST_EPIC_ID = 42
TEST_EPIC_REF = f"YOK-{TEST_EPIC_ID}"


def _upsert_set(*columns: str) -> str:
    return ", ".join(f"{column} = excluded.{column}" for column in columns)


ITEM_UPSERT_SET = _upsert_set(
    "title",
    "workflow_id",
    "workflow_version_id",
    "status",
    "priority",
    "frozen",
    "created_at",
    "updated_at",
    "project_id",
    "project_sequence",
)
PROJECT_UPSERT_SET = _upsert_set("slug", "name", "github_repo")
HARNESS_SESSION_UPSERT_SET = _upsert_set(
    "executor",
    "provider",
    "model",
    "execution_lane",
    "executor_version",
    "machine_id",
    "workspace",
    "mode",
    "offered_at",
    "last_heartbeat",
)
EPIC_TASK_UPSERT_SET = _upsert_set(
    "title",
    "item_worktree_id",
    "status",
    "github_issue",
    "context_estimate",
    "dispatch_attempts",
    "max_attempts",
    "dependencies",
)

MOCK_GH_DEFAULT = textwrap.dedent("""\
    #!/usr/bin/env sh
    _log_file="$MOCK_GH_LOG"
    echo "ARGS=$*" >> "$_log_file"
    case "$1" in
      auth) exit 0 ;;
      label) exit 0 ;;
      issue)
        case "$2" in
          close) echo "Closed issue $3" ; exit 0 ;;
          reopen) echo "Reopened issue $3" ; exit 0 ;;
          edit) echo "Edited issue $3" ; exit 0 ;;
          comment) exit 0 ;;
          view)
            _state="${MOCK_GH_ISSUE_STATE:-OPEN}"
            case "$*" in
              *--json*)
                case "$*" in
                  *--jq*)
                    case "$*" in
                      *state*) echo "$_state" ; exit 0 ;;
                      *labels*) echo "" ; exit 0 ;;
                      *body*) echo "" ; exit 0 ;;
                    esac ;;
                  *)
                    case "$*" in
                      *state*) echo "{\\"state\\": \\"$_state\\"}" ; exit 0 ;;
                      *labels*) echo "{\\"labels\\": []}" ; exit 0 ;;
                      *body*) echo "{\\"body\\": \\"\\"}" ; exit 0 ;;
                    esac ;;
                esac ;;
              *) echo "state: $_state" ; exit 0 ;;
            esac ;;
          list) echo "[]" ; exit 0 ;;
          *) exit 0 ;;
        esac ;;
      *) exit 0 ;;
    esac
""")

MOCK_GH_RETRY = textwrap.dedent("""\
    #!/usr/bin/env sh
    exec gh "$@"
""")
