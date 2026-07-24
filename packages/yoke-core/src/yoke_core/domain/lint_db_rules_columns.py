"""Column-validation fragment for HOOK_POLICY_SOURCE.

Holds RULE_TEXT_COLUMNS — Check 7b (renamed table names) and
Check 8 (wrong SQL column names) via the static blocklist.
"""

from __future__ import annotations

__all__ = ("RULE_TEXT_COLUMNS",)

RULE_TEXT_COLUMNS = r"""
# --- Check 7b: Renamed table names ---
# Detect usage of old table names that have been renamed.
if "# lint:no-column-check" not in command_stripped:
    _RENAMED_TABLES = [
        ("active_sessions", "harness_sessions"),
    ]
    for qs in quoted_strings:
        _qs_lower = qs.lower()
        for _old_name, _new_name in _RENAMED_TABLES:
            _tbl_pat = r"(?<![a-zA-Z_])" + re.escape(_old_name) + r"(?![a-zA-Z_])"
            if re.search(_tbl_pat, _qs_lower):
                result = {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": (
                            "BLOCKED: Stale table name in SQL query.\n"
                            "  Table '%s' was renamed to '%s'.\n"
                            "  See db-reference.md for current schema."
                        ) % (_old_name, _new_name),
                    }
                }
                print(json.dumps(result))
                sys.exit(0)

# --- Check 8: Wrong SQL column names ---
# Detect common wrong column names when the table is identifiable in the query.
# Only blocks when both the table name AND the wrong column appear in the same
# quoted SQL string. This avoids false positives on bare column names that
# could belong to any table.
# Suppression: add "# lint:no-column-check" comment to the command.
if "# lint:no-column-check" not in command_stripped:
    # Blocklist: (table, wrong_column) -> correct_column (or advice)
    _COLUMN_BLOCKLIST = [
        ("events", "type", "event_name"),
        ("events", "timestamp", "created_at"),
        ("events", "source", "source_type"),
        ("events", "detail", "envelope JSON path via Postgres #>> operator"),
        ("events", "context", "envelope JSON path via Postgres #>> operator"),
        ("events", "worker", "no such column — extract from envelope with Postgres JSON operator"),
        ("events", "payload", "envelope"),
        ("ouroboros_entries", "entry", "body"),
        ("ouroboros_entries", "timestamp", "created_at"),
        ("event_registry", "name", "event_name"),
        ("deployment_flows", "flow_id", "id"),
        ("deployment_flows", "item_id", "no such column"),
        ("shepherd_verdicts", "item_id", "item"),
        ("shepherd_verdicts", "gate", "transition"),
        ("epic_tasks", "item_id", "epic_id"),
        ("epic_tasks", "task_number", "task_num"),
        ("epic_tasks", "depends_on", "dependencies"),
        ("epic_progress_notes", "note", "body"),
        ("deployment_runs", "item_id", "no such column — join through deployment_run_items"),
        ("deployment_run_items", "id", "no id column — composite PK: run_id + item_id"),
        ("deployment_run_items", "deploy_stage", "junction table only — stage lives on items.deploy_stage (via python3 -m yoke_core.cli.db_router items update N deploy_stage VAL)"),
        ("deployment_run_items", "current_stage", "junction table only — stage lives on deployment_runs.current_stage (via python3 -m yoke_core.domain.deployment_runs update RUN current_stage VAL)"),
        ("deployment_run_items", "status", "junction table only — status lives on items.status or deployment_runs.status"),
        ("events", "outcome", "event_outcome"),
        ("qa_runs", "requirement_id", "qa_requirement_id"),
        ("qa_runs", "req_id", "qa_requirement_id"),
        ("project_capabilities", "capability", "type"),
        ("project_capabilities", "name", "type"),
        ("project_capabilities", "capability_type", "type"),
        ("projects", "project_id", "id"),
        ("projects", "repo_path", "no shared checkout path column"),
        ("projects", "path", "no shared checkout path column"),
        ("projects", "repo", "no shared checkout path column"),
        ("projects", "repo_url", "github_repo"),
        ("projects", "github_url", "github_repo"),
    ]
    # Strip single-quoted string literals BEFORE static-blocklist
    # matching so column names that legitimately appear inside SQL string
    # values — most notably JSON-payload lookups like ``'{context,pr_num}'`` —
    # are not false-flagged as wrong-column references.  The static
    # blocklist is the only path that matches against raw SQL.
    _sq_re_static = re.compile(chr(39) + r"[^" + chr(39) + r"]*" + chr(39))
    for qs in quoted_strings:
        _qs_for_match = _sq_re_static.sub("", qs)
        _qs_lower = _qs_for_match.lower()
        for _tbl, _wrong, _correct in _COLUMN_BLOCKLIST:
            # Table must appear in the SQL (as word boundary match)
            if _tbl not in _qs_lower:
                continue
            # Wrong column must appear as a word (not substring of another column)
            # Match: word boundary before, followed by non-alphanumeric or end
            _col_pat = r"(?<![a-zA-Z_])" + re.escape(_wrong) + r"(?![a-zA-Z_])"
            if re.search(_col_pat, _qs_for_match, re.IGNORECASE):
                result = {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": (
                            "BLOCKED: Wrong column name in SQL query.\n"
                            "  Table %s%s%s has no column %s%s%s — use %s%s%s instead.\n"
                            "  See .yoke/docs/db-reference.md § Common column mistakes to avoid in raw SQL."
                        ) % (
                            chr(39), _tbl, chr(39),
                            chr(39), _wrong, chr(39),
                            chr(39), _correct, chr(39),
                        ),
                    }
                }
                print(json.dumps(result))
                sys.exit(0)

"""
