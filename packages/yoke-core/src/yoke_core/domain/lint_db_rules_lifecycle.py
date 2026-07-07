"""Lifecycle-mutation fragments for HOOK_POLICY_SOURCE.

* RULE_TEXT_DONE — Check 9 (block direct status=done writes; YOKE_FORCE
  / YOKE_DONE_RECOVERY override guard).
* RULE_TEXT_ADD_PROJECT — Check 14 (advisory: items add without --project).
* RULE_TEXT_LIFECYCLE — Check 10 (qa-db.sh browser_substrate run-add),
  the shared _LIFECYCLE_TABLES / _EVENT_TABLE definitions, Check 15
  (lifecycle DML via raw DB query), Check 15b (lifecycle mutation in
  inline Python).
"""

from __future__ import annotations

__all__ = (
    "RULE_TEXT_ADD_PROJECT",
    "RULE_TEXT_DONE",
    "RULE_TEXT_LIFECYCLE",
)

RULE_TEXT_DONE = r"""
# --- Check 9: Block direct status=done writes ---
# Setting status=done must go through done-transition.sh (via /yoke usher YOK-N).
# Direct calls bypass merge, cleanup, deploy, and release notes.
# Suppression: add "# lint:no-done-check" comment to the command.
# Separate force-override check below intentionally has NO suppression path for
# assistant-issued commands. Operator overrides should be performed manually.
_force_override_pat = re.compile(
    r"(?:^|[\s;])(?:export\s+)?(?:YOKE_FORCE|YOKE_DONE_RECOVERY)=(?:1|\"1\")\b"
)
_force_state_mutation_pat = re.compile(
    r"(?:yoke-db\.sh\s+items\s+update|backlog-registry\.sh\s+update|"
    r"epic-db\.sh\s+\S+|done-transition\.sh\b)"
)
if _force_override_pat.search(command_stripped) and _force_state_mutation_pat.search(command_stripped):
    result = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "BLOCKED: Do not use YOKE_FORCE or YOKE_DONE_RECOVERY from assistant-issued commands.\n"
                "This is an operator override for manual recovery only.\n"
                "Run the normal ceremony (/yoke usher or /yoke advance path), "
                "or ask the user to perform the override manually if recovery is truly required."
            ),
        }
    }
    print(json.dumps(result))
    sys.exit(0)

if "status" in command and "done" in command and "# lint:no-done-check" not in command_stripped:
    # Match legacy direct item-update commands that set status=done.
    # Also match: backlog-registry.sh update N status done
    _done_pat = re.compile(
        r"(?:yoke-db\.sh\s+items\s+update|backlog-registry\.sh\s+update)"
        r"\s+\S+\s+status\s+done\b"
    )
    if _done_pat.search(command_stripped):
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "BLOCKED: Do not set status=done directly.\n"
                    "Use: /yoke usher YOK-N\n"
                    "The done-transition ceremony handles merge, cleanup, deploy, "
                    "release notes, and GitHub sync.\n"
                    "Add %s# lint:no-done-check%s comment to suppress "
                    "if you understand the risks."
                ) % (chr(39), chr(39)),
            }
        }
        print(json.dumps(result))
        sys.exit(0)

# Check 12 (block direct status=passed writes) removed — `passed` is
# no longer a canonical status. The `# lint:no-passed-check` bypass is also retired.

"""
RULE_TEXT_ADD_PROJECT = r"""
# --- Check 14: Advisory for items add without --project ---
# Automated ticket creation (conduct gap tickets, curate, import) should always
# pass --project explicitly; repo config no longer defines project context.
# Suppression: add "# lint:no-project-check" comment to the command.
if "items" in command and "add" in command and "# lint:no-project-check" not in command_stripped:
    _items_add_pat = re.compile(
        r"yoke-db\.sh\s+items\s+add\b"
    )
    if _items_add_pat.search(command_stripped) and "--project" not in command_stripped:
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": (
                    "WARNING: items add called without --project.\n"
                    "Without --project, the item cannot inherit project context "
                    "from repo config. For automated ticket creation (conduct "
                    "gap tickets, curate promotions, bulk imports), always pass "
                    "--project explicitly to inherit the correct project scope.\n"
                    "Add %s# lint:no-project-check%s comment to suppress this warning."
                    % (chr(39), chr(39))
                ),
            }
        }
        print(json.dumps(result))
        sys.exit(0)

"""
RULE_TEXT_LIFECYCLE = r"""
# --- Check 10: Block direct qa-db.sh browser_substrate run-add ---
# Browser-kind QA runs must come from browser-run-scenario.sh, not direct
# qa-db.sh calls. Direct calls allow agents to fabricate passing runs.
# Suppression: add "# lint:no-browser-run-check" comment to the command.
if "qa-db.sh" in command and "browser_substrate" in command and "# lint:no-browser-run-check" not in command_stripped:
    _browser_run_pat = re.compile(
        r"qa-db\.sh\s+run-add\b.*--executor-type\s+[" + chr(39) + r"\"]?browser_substrate[" + chr(39) + r"\"]?"
    )
    if _browser_run_pat.search(command_stripped):
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "BLOCKED: Do not record browser_substrate runs directly via qa-db.sh.\n"
                    "Browser QA runs must come from the canonical orchestrator:\n"
                    "  python3 -m yoke_core.domain.browser_qa --item-id N ...\n"
                    "Direct qa-db.sh run-add calls with executor_type=browser_substrate can\n"
                    "fabricate passing runs that bypass the QA gate.\n"
                    "Add %s# lint:no-browser-run-check%s comment to suppress if called from "
                    "yoke_core.domain.browser_qa or a test harness."
                ) % (chr(39), chr(39)),
            }
        }
        print(json.dumps(result))
        sys.exit(0)

# --- Lifecycle table definitions (shared by Check 15 and Check 15b) ---
# Defined unconditionally so Check 15b can reference them even when
# Check 15a's raw-query gate does not fire. Previously these lived
# inside the Check 15 `if` block and any command that reached Check 15b via a
# python heredoc would crash with NameError. The retired shell test masked this
# because a Python crash produces empty stdout, which its assert_allows helper
# interpreted as ALLOW.
_LIFECYCLE_TABLES = {
    "items": {"status", "deploy_stage"},
    "epic_tasks": {"status"},
}
_EVENT_TABLE = "events"

# --- Check 15: Block lifecycle-sensitive DML via raw DB query ---
# Mutations on lifecycle-owned tables/columns via the query escape hatch bypass
# status validation, event emission, derived-view refresh, and GitHub sync.
# Targets: UPDATE/DELETE on items (status column), UPDATE/DELETE on epic_tasks (status column),
# INSERT/UPDATE/DELETE on events (events must go through the sanctioned emitter).
# Suppression: add "# lint:no-lifecycle-mutation-check" comment to the command.
if uses_raw_query_escape_hatch(command) and "# lint:no-lifecycle-mutation-check" not in command_stripped:
    _lifecycle_sql_strings = []
    for _candidate in extract_yoke_query_sql_payloads(command) + re.findall(r"\"((?:[^\"\\]|\\.)*)\"", command):
        if _candidate not in _lifecycle_sql_strings:
            _lifecycle_sql_strings.append(_candidate)
    for _dqs in _lifecycle_sql_strings:
        _dqs_upper = _dqs.upper()
        # Check for DML on the events table (all writes must go through the sanctioned emitter)
        if re.search(r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+" + _EVENT_TABLE + r"\b", _dqs, re.IGNORECASE):
            result = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        "BLOCKED: Do not write to the events table via db_router query.\n"
                        "Events must go through the sanctioned emitter:\n"
                        "  python3 -m yoke_core.domain.emit_event --event-name <NAME> ...\n"
                        "Direct writes bypass event-registry validation, envelope structure, and audit trail.\n"
                        "Add %s# lint:no-lifecycle-mutation-check%s to suppress for legitimate repair."
                    ) % (chr(39), chr(39)),
                }
            }
            print(json.dumps(result))
            sys.exit(0)
        # Check for UPDATE/DELETE on lifecycle-owned tables touching status columns
        for _lt_table, _lt_cols in _LIFECYCLE_TABLES.items():
            # Match UPDATE <table> SET ... <col> = ...
            _update_match = re.search(
                r"\bUPDATE\s+" + _lt_table + r"\b\s+SET\b(.*?)(?:\bWHERE\b|$)",
                _dqs, re.IGNORECASE | re.DOTALL
            )
            if _update_match:
                _set_clause = _update_match.group(1)
                for _lc in _lt_cols:
                    if re.search(r"\b" + _lc + r"\b\s*=", _set_clause, re.IGNORECASE):
                        _repair_hint = (
                            "  python3 -m yoke_core.api.service_client backlog-cli update YOK-<id> status <status>\n"
                            if _lt_table == "items" else
                            "  python3 -m yoke_core.domain.epic task-update-status <epic-id> <task-num> <status>\n"
                        )
                        result = {
                            "hookSpecificOutput": {
                                "hookEventName": "PreToolUse",
                                "permissionDecision": "deny",
                                "permissionDecisionReason": (
                                    "BLOCKED: Do not mutate %s.%s via db_router query.\n"
                                    "Lifecycle-sensitive columns must go through sanctioned mutators:\n%s"
                                    "For emergency repair: python3 -m yoke_core.engines.repair_status <id> <status>\n"
                                    "Direct writes bypass status validation, lifecycle events, and derived-view refresh.\n"
                                    "Add %s# lint:no-lifecycle-mutation-check%s to suppress for legitimate repair."
                                ) % (_lt_table, _lc, _repair_hint, chr(39), chr(39)),
                            }
                        }
                        print(json.dumps(result))
                        sys.exit(0)
            # Match DELETE FROM <table>
            if re.search(r"\bDELETE\s+FROM\s+" + _lt_table + r"\b", _dqs, re.IGNORECASE):
                result = {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": (
                            "BLOCKED: Do not DELETE from %s via db_router query.\n"
                            "Row deletion on lifecycle-owned tables bypasses cleanup, events, and derived-view refresh.\n"
                            "For emergency repair: python3 -m yoke_core.engines.repair_status <id> <status>\n"
                            "Add %s# lint:no-lifecycle-mutation-check%s to suppress for legitimate repair."
                        ) % (_lt_table, chr(39), chr(39)),
                    }
                }
                print(json.dumps(result))
                sys.exit(0)

# --- Check 15b: Block lifecycle-sensitive mutations in inline Python ---
# Inline Python that uses sqlite3 to mutate lifecycle-owned tables is already partially
# caught by Check 1 (hardcoded yoke.db). This check catches Python that receives the
# DB path as an argument or env var and mutates lifecycle tables.
# Reuses extract_python_payloads() from the heredoc/inline preprocessing above.
for py_code in extract_python_payloads(original_command):
    if "# lint:no-lifecycle-mutation-check" in original_command:
        break
    _py_upper = py_code.upper()
    for _lt_table in list(_LIFECYCLE_TABLES.keys()) + [_EVENT_TABLE]:
        if re.search(r"\b(UPDATE\s+" + _lt_table + r"|INSERT\s+INTO\s+" + _lt_table + r"|DELETE\s+FROM\s+" + _lt_table + r")\b", py_code, re.IGNORECASE):
            result = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        "BLOCKED: Inline Python mutates lifecycle-owned table %s%s%s.\n"
                        "Lifecycle mutations must go through sanctioned mutators "
                        "(service_client backlog-cli update, domain.epic task-update-status, domain.emit_event).\n"
                        "For emergency repair: python3 -m yoke_core.engines.repair_status <id> <status>\n"
                        "Add %s# lint:no-lifecycle-mutation-check%s to suppress for legitimate repair."
                    ) % (chr(39), _lt_table, chr(39), chr(39), chr(39)),
                }
            }
            print(json.dumps(result))
            sys.exit(0)

"""
