"""Operator-syntax fragments for HOOK_POLICY_SOURCE.

* RULE_TEXT_SQLITE3 — Check 1a (pipe-to-shell with sqlite3 in quotes),
  Check 1 (direct sqlite3 binary calls).
* RULE_TEXT_DDL_GATE — Check 11 (DDL via db_router query) and the gate
  for Check 2 onward (extracts quoted_strings; early-returns when the
  command is not a raw DB query).
* RULE_TEXT_OPERATORS_CMP — Check 2a (! = operator) and
  Check 2b (escaped comparison operators).
"""
from __future__ import annotations
RULE_TEXT_SQLITE3 = r"""
# --- Check 1a: Pipe-to-shell with sqlite3 in quoted content ---
# Even after quote stripping, detect sqlite3 inside quoted strings being piped
# to shell executors (sh, bash, zsh). The quoted content IS the dangerous payload.
# Must check original command since the keyword is inside quotes.
if "sqlite3" in command and "|" in command:
    _PIPE_SHELL_EXECUTORS = {"sh", "bash", "zsh"}
    _pipe_segs = command.split("|")
    if len(_pipe_segs) > 1:
        for _ps in _pipe_segs[1:]:
            _ps_first = _ps.strip().split()[0] if _ps.strip().split() else ""
            _ps_first = _ps_first.rsplit("/", 1)[-1] if "/" in _ps_first else _ps_first
            if _ps_first in _PIPE_SHELL_EXECUTORS:
                result = {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": (
                            "BLOCKED: Do not call sqlite3 directly. "
                            "Use the Python DB router instead. Examples:\n"
                            "  python3 -m yoke_core.cli.db_router items get YOK-N status\n"
                            "  python3 -m yoke_core.cli.db_router query \"SELECT ...\"\n"
                            "See AGENTS.md § Code Conventions (DB rules)."
                        ),
                    }
                }
                print(json.dumps(result))
                sys.exit(0)

# --- Check 1: Direct sqlite3 calls ---
# Block direct sqlite3 binary invocations, but allow:
# (a) Invoking allowlisted scripts that have "sqlite3" in their filename
# (b) Non-executable references (grep, cat, find, etc.) mentioning "sqlite3"
# Fail-closed: if the allowlist logic cannot determine safety, block.
if "sqlite3" in command_stripped:
    # Scripts known to contain "sqlite3" in their filename.
    # These are safe to invoke directly. To add a new script, add one
    # entry here — no other changes needed.
    SQLITE3_ALLOWLIST = {
        # PostToolUse hook and lint hook (self-reference in testing)
        "sqlite3-error-hook.sh",
        "lint-sqlite-cmd.sh",
        "test-lint-sqlite-cmd.sh",
        # Supported migration scripts
        "migrate-to-sqlite.sh",
        "test-migrate-to-sqlite.sh",
    }

    # Commands that reference files/strings but do not execute them.
    # These are safe contexts for "sqlite3" to appear as an argument.
    # Selection criteria: each command reads, searches, or displays data
    # but cannot execute arbitrary code from its arguments. Commands like
    # sh, bash, python3, eval, xargs are intentionally excluded.
    READ_ONLY_CMDS = {
        "grep", "rg", "cat", "head", "tail", "wc", "diff",
        "less", "find", "ls", "echo", "printf",
    }

    # Step 1: Extract .sh basenames from the command and remove
    # allowlisted ones from a residual copy. If no "sqlite3" remains
    # in the residual, all references are accounted for — allow.
    scripts_in_cmd = set(re.findall(r"[\w.-]+\.sh", command_stripped))
    residual = command_stripped
    for script in (scripts_in_cmd & SQLITE3_ALLOWLIST):
        residual = residual.replace(script, "")
    if "sqlite3" not in residual:
        # All "sqlite3" occurrences came from allowlisted script names
        pass  # fall through to Check 2
    else:
        # Step 1b: Pipe-to-shell safety check. If "sqlite3" appears
        # in a command piped to a shell executor (sh, bash, zsh),
        # a read-only cmd like echo could construct executable code.
        # Block these patterns regardless of read-only first-word.
        SHELL_EXECUTORS = {"sh", "bash", "zsh"}
        pipe_segments = residual.split("|")
        if len(pipe_segments) > 1:
            for seg in pipe_segments[1:]:
                seg_first = seg.strip().split()[0] if seg.strip().split() else ""
                seg_first = seg_first.rsplit("/", 1)[-1] if "/" in seg_first else seg_first
                if seg_first in SHELL_EXECUTORS:
                    result = {
                        "hookSpecificOutput": {
                            "hookEventName": "PreToolUse",
                            "permissionDecision": "deny",
                            "permissionDecisionReason": (
                                "BLOCKED: Do not call sqlite3 directly. "
                                "Use the Python DB router instead. Examples:\n"
                                "  python3 -m yoke_core.cli.db_router items get YOK-N status\n"
                                "  python3 -m yoke_core.cli.db_router query \"SELECT ...\"\n"
                                "See AGENTS.md § Code Conventions (DB rules)."
                            ),
                        }
                    }
                    print(json.dumps(result))
                    sys.exit(0)

        # Step 2: Split residual on compound operators to detect
        # sqlite3 as an invoked binary/script in any sub-command. A branch,
        # path, or other inert argument may still contain the token (for
        # example ``git merge-tree ... runtime-sqlite3-triage``); only
        # executable-position matches are unsafe here.
        # Handles: &&, ||, ;, |, $( subshell
        parts = re.split(r"[;&|\n]+|\$\(", residual)

        def _sqlite3_invoked_in_part(part):
            try:
                words = shlex.split(part, posix=True)
            except Exception:
                words = part.split()
            idx = 0
            while idx < len(words) and re.match(r"[A-Za-z_]\w*=.*", words[idx]):
                idx += 1
            if idx >= len(words):
                return False
            first_word = words[idx].rsplit("/", 1)[-1]
            if first_word == "sqlite3":
                return True
            if first_word == "command" and idx + 1 < len(words):
                return words[idx + 1].rsplit("/", 1)[-1] == "sqlite3"
            if first_word == "env":
                nested_idx = idx + 1
                while (
                    nested_idx < len(words)
                    and re.match(r"[A-Za-z_]\w*=.*", words[nested_idx])
                ):
                    nested_idx += 1
                return (
                    nested_idx < len(words)
                    and words[nested_idx].rsplit("/", 1)[-1] == "sqlite3"
                )
            if first_word in SHELL_EXECUTORS:
                for token in words[idx + 1:]:
                    if token.startswith("-"):
                        continue
                    script = token.rsplit("/", 1)[-1]
                    return "sqlite3" in script
            return False

        blocked = False
        for part in parts:
            part = part.strip()
            if "sqlite3" not in part:
                continue
            # Determine the first word (the command being invoked)
            words = part.split()
            first_word = words[0] if words else ""
            # Strip leading path components to get basename
            first_word = first_word.rsplit("/", 1)[-1] if "/" in first_word else first_word
            if first_word in READ_ONLY_CMDS:
                continue  # safe read-only context
            if _sqlite3_invoked_in_part(part):
                blocked = True
                break
        if not blocked:
            pass  # fall through to Check 2
        else:
            result = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        "BLOCKED: Do not call sqlite3 directly. "
                        "Use the Python DB router instead. Examples:\n"
                        "  python3 -m yoke_core.cli.db_router items get YOK-N status\n"
                        "  python3 -m yoke_core.cli.db_router query \"SELECT ...\"\n"
                        "See AGENTS.md § Code Conventions (DB rules)."
                    ),
                }
            }
            print(json.dumps(result))
            sys.exit(0)


"""
RULE_TEXT_DDL_GATE = r"""
# --- Check 11: Hard-deny DDL in raw DB query ---
# Schema-modifying statements (ALTER TABLE, CREATE TABLE, DROP TABLE) and
# dangerous PRAGMA toggles via the raw-query escape hatch are
# BLOCKED.  All destructive/schema-rebuilding migrations must route through
# the governed migration harness (yoke_core.domain.migration_harness).
# Suppression: add "# lint:no-ddl-check" comment to the command.
if uses_raw_query_escape_hatch(command) and "# lint:no-ddl-check" not in command_stripped:
    _ddl_pat = re.compile(
        r"\b(ALTER\s+TABLE|CREATE\s+TABLE|DROP\s+TABLE)\b",
        re.IGNORECASE
    )
    _pragma_pat = re.compile(
        r"\bPRAGMA\s+(foreign_keys\s*=\s*OFF|journal_mode\s*=\s*OFF|synchronous\s*=\s*OFF)\b",
        re.IGNORECASE
    )
    for _dqs in re.findall(r"\"((?:[^\"\\]|\\.)*)\"", command):
        if _ddl_pat.search(_dqs):
            _ddl_match = _ddl_pat.search(_dqs).group(1)
            result = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        "BLOCKED: DDL statement (%s) detected in db_router query.\n"
                        "DDL through the query escape hatch is denied.\n"
                        "All schema-modifying migrations must route through the governed\n"
                        "migration harness (yoke_core.domain.migration_harness).\n"
                        "Use python3 -m yoke_core.domain.schema init for registered migrations.\n"
                        "Suppression: %s# lint:no-ddl-check%s (emergency only)."
                    ) % (_ddl_match, chr(39), chr(39)),
                }
            }
            print(json.dumps(result))
            sys.exit(0)
        if _pragma_pat.search(_dqs):
            _pragma_match = _pragma_pat.search(_dqs).group(0)
            result = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        "BLOCKED: Dangerous PRAGMA (%s) detected in db_router query.\n"
                        "Disabling safety guarantees (foreign_keys, journal_mode, synchronous)\n"
                        "outside the governed migration harness is denied.\n"
                        "Suppression: %s# lint:no-ddl-check%s (emergency only)."
                    ) % (_pragma_match, chr(39), chr(39)),
                }
            }
            print(json.dumps(result))
            sys.exit(0)

# --- Check 2: Dangerous SQL operators in raw DB query commands ---
# zsh histexpand converts != to \!= even in the non-interactive Bash tool
# shell, and the backslash reaches the SQL parser causing an invalid token.
# Also blocks \>=, \<=, \>, \< (backslash is literal SQL text).
if not uses_raw_query_escape_hatch(command_stripped):
    sys.exit(0)

# Extract SQL strings from raw DB query invocations using shell parsing so
# single-quoted SQL is inspected too. Keep the quoted-string fallback so checks
# still see inline SQL assigned to variables earlier in the command.
quoted_strings = []
for _candidate in extract_yoke_query_sql_payloads(command) + re.findall(r"\"((?:[^\"\\]|\\.)*)\"", command):
    if _candidate not in quoted_strings:
        quoted_strings.append(_candidate)

"""
RULE_TEXT_OPERATORS_CMP = r"""
# --- Check 2a: != operator (must use <> instead) ---
# Both bare != and \!= are blocked because zsh delivers \!= either way.
for qs in quoted_strings:
    if re.search(r"\\?!=", qs):
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "BLOCKED: SQL contains != operator. "
                    "Use <> instead of != — zsh histexpand converts != "
                    "to \\!= which the SQL parser rejects as an invalid token. "
                    "The <> operator is SQL-standard and immune to zsh mangling.\n"
                    "Example: WHERE status <> " + chr(39) + "done" + chr(39) + "  (not: WHERE status != " + chr(39) + "done" + chr(39) + ")"
                ),
            }
        }
        print(json.dumps(result))
        sys.exit(0)

# --- Check 2b: Escaped comparison operators (\>=, \<=, \>, \<) ---
# Pattern: literal backslash followed by an operator
# Order matters: check two-char operators before single-char ones
patterns = [
    (r"\\>=", r"\>="),
    (r"\\<=", r"\<="),
    (r"\\>",  r"\>"),
    (r"\\<",  r"\<"),
]

for regex, display in patterns:
    for qs in quoted_strings:
        if re.search(regex, qs):
            result = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        "BLOCKED: command contains escaped operator \"%s\". "
                        "Use unescaped operators (>=, <=, >, <) or <> for not-equal — "
                        "backslash is literal SQL text. "
                        "See AGENTS.md § Code Conventions (DB rules)."
                    ) % display,
                }
            }
            print(json.dumps(result))
            sys.exit(0)

sys.exit(0)
"""

__all__ = (
    "RULE_TEXT_DDL_GATE",
    "RULE_TEXT_OPERATORS_CMP",
    "RULE_TEXT_SQLITE3",
)
