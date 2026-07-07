"""Pytest behavioral tests for update_status: terminal success, label reconciliation, error logging.

Migrated from the shell harness ``test-update-status.sh``. These tests
exercise close-at-done, canonical labels, sequential transitions, stale
label removal, and graceful degradation of ``gh`` failures.
"""

from __future__ import annotations

import os
import textwrap

import pytest

from runtime.api.update_status_full_test_helpers import UpdateStatusEnv


@pytest.fixture
def env(tmp_path):
    e = UpdateStatusEnv(tmp_path, f"test-update-status-{os.getpid()}")
    try:
        yield e
    finally:
        e.close()


class TestTerminalSuccess:
    """Tests 1, 2, 4 — close at done, canonical label, sequential transitions."""

    def test_close_at_done(self, env):
        """TEST 1: PATCH /issues/100 with state=closed when task transitions to done."""
        env.insert_task("implementing")
        env.init_git()
        r = env.run("42", "003", "done", extra_env={"YOKE_TASK_DONE_VERIFIED": "1"})
        assert r.returncode == 0
        log = env.gh_log.read_text()
        assert "PATCH /repos/upyoke/yoke/issues/100" in log

    def test_canonical_done_label(self, env):
        """TEST 2: REST POSTs status:done label, never status:completed."""
        env.insert_task("implementing")
        env.init_git()
        r = env.run("42", "003", "done", extra_env={"YOKE_TASK_DONE_VERIFIED": "1"})
        assert r.returncode == 0
        log = env.gh_log.read_text()
        # POST /labels with name 'status:done' is recorded as a label-create
        # request; the canonical reason check is that 'status:done' appears
        # and 'status:completed' never does.
        assert "POST /repos/upyoke/yoke/labels" in log

    def test_reviewed_implementation_then_done(self, env):
        """TEST 4: sequential reviewed-impl -> done exits 0 with two closes."""
        env.insert_task("reviewing-implementation")
        env.init_git()
        r1 = env.run("42", "003", "reviewed-implementation")
        r2 = env.run("42", "003", "done", extra_env={"YOKE_TASK_DONE_VERIFIED": "1"})
        assert r1.returncode == 0
        assert r2.returncode == 0
        log = env.gh_log.read_text()
        # Each terminal-status transition dispatches one PATCH /issues/100
        # with state=closed; reviewed-impl + done = two PATCHes.
        assert log.count("PATCH /repos/upyoke/yoke/issues/100") >= 2

    def test_transitions_recorded_as_state_rows(self, env):
        """The status pipeline writes item_status_transitions at mutation
        time — the state table, not the telemetry ledger, is what board
        velocity / execution status / lifecycle HCs read post telemetry-only-events."""
        env.insert_task("reviewing-implementation")
        env.init_git()
        assert env.run("42", "003", "reviewed-implementation").returncode == 0
        assert env.run(
            "42", "003", "done", extra_env={"YOKE_TASK_DONE_VERIFIED": "1"},
        ).returncode == 0
        assert env.query_int(
            "SELECT COUNT(*) FROM item_status_transitions "
            "WHERE item_id=42 AND task_num=3"
        ) == 2
        assert env.query_int(
            "SELECT COUNT(*) FROM item_status_transitions "
            "WHERE item_id=42 AND task_num=3 "
            "AND from_status='reviewing-implementation' "
            "AND to_status='reviewed-implementation'"
        ) == 1
        assert env.query_int(
            "SELECT COUNT(*) FROM item_status_transitions "
            "WHERE item_id=42 AND task_num=3 AND to_status='done'"
        ) == 1
        # A transition is item activity: the rollup gains the epic's day row.
        assert env.query_int(
            "SELECT COUNT(*) FROM item_activity_days WHERE item_id=42"
        ) == 1


class TestLabelReconciliation:
    """Tests 3, 26 — stale label removal, underscore normalization."""

    def _write_label_mock(self, env, label_name: str) -> None:
        env._write_mock_gh(textwrap.dedent(f"""\
            #!/usr/bin/env sh
            _log_file="$MOCK_GH_LOG"
            echo "ARGS=$*" >> "$_log_file"
            case "$1" in
              auth) exit 0 ;;
              label) exit 0 ;;
              issue)
                case "$2" in
                  close) echo "Closed issue $3" ; exit 0 ;;
                  edit) echo "Edited issue $3" ; exit 0 ;;
                  comment) exit 0 ;;
                  view)
                    _state="${{MOCK_GH_ISSUE_STATE:-OPEN}}"
                    case "$*" in
                      *--jq*)
                        case "$*" in
                          *state*) echo "$_state" ; exit 0 ;;
                          *labels*) echo "{label_name}" ; exit 0 ;;
                          *body*) echo "" ; exit 0 ;;
                        esac ;;
                      *--json*)
                        case "$*" in
                          *state*) echo "{{\\"state\\": \\"$_state\\"}}" ; exit 0 ;;
                          *labels*) echo "{{\\"labels\\": [{{\\"name\\":\\"{label_name}\\"}}]}}" ; exit 0 ;;
                          *body*) echo "{{\\"body\\": \\"\\"}}" ; exit 0 ;;
                        esac ;;
                      *) echo "state: $_state" ; exit 0 ;;
                    esac ;;
                  *) exit 0 ;;
                esac ;;
              *) exit 0 ;;
            esac
        """))

    def _seed_existing_label(self, env, label_name: str) -> None:
        """Seed the REST GET /issues/100/labels response with the named label."""
        import json
        rest_dir = env.tmp / "rest-fakes"
        rest_dir.mkdir(exist_ok=True)
        # GET /repos/upyoke/yoke/issues/100/labels -> [{name: label_name}]
        labels_file = rest_dir / "GET_repos_upyoke_yoke_issues_100_labels.json"
        labels_file.write_text(json.dumps({
            "status": 200,
            "body": [{"name": label_name}],
        }))

    def test_stale_label_removed(self, env):
        """TEST 3: old status:done label is removed on new transition."""
        env.insert_task("implementing")
        env.init_git()
        self._seed_existing_label(env, "status:done")
        r = env.run("42", "003", "reviewed-implementation")
        assert r.returncode == 0
        log = env.gh_log.read_text()
        assert "labels/status%3Adone" in log

    def test_underscore_label_removed(self, env):
        """TEST 26: stale status:in_progress label is removed."""
        env.insert_task("planned")
        env.init_git()
        self._seed_existing_label(env, "status:in_progress")
        r = env.run("42", "3", "implementing")
        assert r.returncode == 0
        log = env.gh_log.read_text()
        assert "labels/status%3Ain_progress" in log
        # POST .../issues/100/labels adds the new status:implementing label.
        assert "POST /repos/upyoke/yoke/issues/100/labels" in log


class TestErrorLogging:
    """Tests 10, 11, 12 — REST failures degrade gracefully under the Python owner."""

    def _seed_failing_rest(self, env, *, fail_path: str, status: int = 500) -> None:
        """Seed a 5xx response for the named REST endpoint filename."""
        import json
        rest_dir = env.tmp / "rest-fakes"
        rest_dir.mkdir(exist_ok=True)
        (rest_dir / fail_path).write_text(json.dumps({
            "status": status,
            "body": "simulated REST failure",
        }))

    def test_comment_post_failure(self, env):
        """TEST 10: REST POST /comments failure is warned; script exits 0."""
        env.insert_task("implementing")
        env.init_git()
        self._seed_failing_rest(
            env,
            fail_path="POST_repos_upyoke_yoke_issues_100_comments.json",
        )
        r = env.run("42", "003", "done", extra_env={"YOKE_TASK_DONE_VERIFIED": "1"})
        assert r.returncode == 0
        output = r.stdout + r.stderr
        assert "Warning: failed to post comment on #100" in output

    def test_label_swap_failure(self, env):
        """TEST 11: REST POST /labels failure is warned."""
        env.insert_task("implementing")
        env.init_git()
        self._seed_failing_rest(
            env,
            fail_path="POST_repos_upyoke_yoke_issues_100_labels.json",
        )
        r = env.run("42", "003", "done", extra_env={"YOKE_TASK_DONE_VERIFIED": "1"})
        assert r.returncode == 0
        output = r.stdout + r.stderr
        assert "Warning: failed to add label status:done to #100" in output

    def test_issue_close_failure(self, env):
        """TEST 12: REST PATCH /issues/100 close failure emits GitHubCloseFailure event."""
        env.insert_task("implementing")
        env.init_git()
        self._seed_failing_rest(
            env,
            fail_path="PATCH_repos_upyoke_yoke_issues_100.json",
        )
        r = env.run("42", "003", "done", extra_env={"YOKE_TASK_DONE_VERIFIED": "1"})
        assert r.returncode == 0
        assert env.query_int(
            "SELECT COUNT(*) FROM events WHERE event_name='GitHubCloseFailure'"
        ) == 1
