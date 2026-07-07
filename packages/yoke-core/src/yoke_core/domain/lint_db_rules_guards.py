"""Guard fragments for HOOK_POLICY_SOURCE.

* RULE_TEXT_GUARDS_INPUT — Check 7 (conflict markers), Check 4 (BSD awk),
  Check 3 (guarded scripts) and the YOKE_SKILL_CONTEXT bypass guard.
* RULE_TEXT_GUARDS_CLI — Check 5 (claude CLI).
* RULE_TEXT_BODY_BANS — Check 13 (raw body writes), Check 13b (ingest-body).
"""

from __future__ import annotations

__all__ = (
    "RULE_TEXT_BODY_BANS",
    "RULE_TEXT_GUARDS_CLI",
    "RULE_TEXT_GUARDS_INPUT",
)

RULE_TEXT_GUARDS_INPUT = r"""
# --- Check 7: Block git commit when Yoke files have conflict markers ---
# Defense in depth: prevent committing conflict markers in Yoke-managed files.
# Only triggers when the command contains "git commit" or "git add" with yoke/ paths.
if ("git commit" in command_stripped or "git add" in command_stripped) and "runtime/" in command_stripped:
    import subprocess
    try:
        _conflict_check = subprocess.run(
            ["grep", "-rlq", "^<<<<<<< \\|^=======$\\|^>>>>>>> ",
             ".yoke/BOARD.md"],
            capture_output=True, timeout=5
        )
        if _conflict_check.returncode == 0:
            result = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        "BLOCKED: Conflict markers detected in Yoke-managed files. "
                        "Resolve conflict markers before committing.\n"
                        "Run: yoke board rebuild\n"
                        "Or:  /yoke doctor --fix --only HC-unformalized-deps"
                    ),
                }
            }
            print(json.dumps(result))
            sys.exit(0)
    except Exception:
        pass  # Non-fatal: do not block on check failure

# --- Check 4: BSD-incompatible awk negation ---
# BSD awk (macOS) does not support !var as a boolean negation in patterns.
# It misparses "!varname" causing silent failures or syntax errors that can
# wipe data (e.g., body content lost when awk fails mid-pipe).
# Correct form: var==0 instead of !var.
if "awk" in command:
    # Extract single-quoted strings (awk programs) after "awk"
    # Note: cannot use literal single quotes inside python3 -c string,
    # so build the regex with chr(39)
    sq = chr(39)
    awk_programs = re.findall(r"awk\s.*?" + sq + r"([^" + sq + r"]+)" + sq, command)
    for prog in awk_programs:
        # Match !variable_name — but NOT != (not-equal) or !~ (regex not-match)
        # or !/ (negated regex literal)
        bad = re.search(r"!([a-zA-Z_]\w*)", prog)
        if bad:
            varname = bad.group(1)
            result = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        "BLOCKED: awk program contains %s!%s%s — BSD awk (macOS) "
                        "does not support !variable as boolean negation. "
                        "Use %s%s==0%s instead of %s!%s%s.\n"
                        "See AGENTS.md: \"BSD awk: skip==0{print} not !skip{print}\""
                    ) % (sq, varname, sq, sq, varname, sq, sq, varname, sq),
                }
            }
            print(json.dumps(result))
            sys.exit(0)

# --- Check 3: Direct calls to guarded scripts ---
# These scripts have business-logic guards (YOKE_SKILL_CONTEXT) that are
# trivially bypassed by setting the env var inline. Instead, enforce at the
# hook level: block any Bash command that directly invokes these scripts.
# Legitimate callers invoke these guards through sanctioned orchestration
# subprocesses, which are invisible to this hook.
# Suppression comment "# lint:no-guard-check" bypasses this check,
# following the same pattern as Check 6 "# lint:no-repo-flag". Used by
# usher SKILL.md to call merge-worktree.sh directly (usher intentionally
# separates merge from done-transition).
_skip_guard_check = "# lint:no-guard-check" in command_stripped
guarded_scripts = {
    "backlog-registry.sh": "the registered item mutation surface",
    "merge-worktree.sh": "done-transition.sh (via /yoke usher), or usher SKILL.md with # lint:no-guard-check",
    "sprint-db.sh": "schema-db.sh / project-db.sh (sprint-db.sh was removed)",
}
# Commands that reference files but do not execute them.
# When a guarded script name appears as an argument to one of these commands,
# it is a file reference (read, search, display, VCS operation) — not an
# invocation. Skip Check 3 for these contexts.
_GUARD_SAFE_CMDS = {
    "grep", "rg", "cat", "head", "tail", "wc", "diff", "less",
    "find", "ls", "echo", "printf", "git", "mv", "cp", "chmod",
    "file", "stat", "md5sum", "shasum",
}
# Split on compound operators (same approach as Check 5 for claude CLI)
_guard_parts = re.split(r"[;&|\n]+|\$\(", command_stripped)
for script, alternative in guarded_scripts.items():
    for _gp in _guard_parts:
        _gp = _gp.strip()
        if not _gp:
            continue
        _gw = _gp.split()
        if not _gw:
            continue
        # Skip leading env var assignments (e.g. VAR=val sh script.sh)
        _gi = 0
        while _gi < len(_gw) and "=" in _gw[_gi] and not _gw[_gi].startswith("="):
            _gi += 1
        if _gi >= len(_gw):
            continue
        # If the command word is a non-executing (read-only / VCS) command,
        # the guarded script name is a file argument, not an invocation.
        _cmd_basename = _gw[_gi].rsplit("/", 1)[-1] if "/" in _gw[_gi] else _gw[_gi]
        if _cmd_basename in _GUARD_SAFE_CMDS:
            continue
        # Check remaining words for exact basename match as invoked script
        for _wi in range(_gi, len(_gw)):
            _basename = _gw[_wi].rsplit("/", 1)[-1] if "/" in _gw[_wi] else _gw[_wi]
            if _basename == script:
                # Allow if suppression comment is present
                if _skip_guard_check:
                    break
                result = {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": (
                            "BLOCKED: Do not call %s directly. "
                            "Use %s instead.\n"
                            "Direct invocation bypasses skill-layer business logic "
                            "(dedup, lifecycle validation, worktree management).\n"
                            "See AGENTS.md and runtime/harness/claude/rules/session.md."
                        ) % (script, alternative),
                    }
                }
                print(json.dumps(result))
                sys.exit(0)
            # Only check command name and its immediate argument (sh script.sh)
            if _wi > _gi:
                break

# Also block YOKE_SKILL_CONTEXT= env var bypass attempts.
# Use segment-aware detection: only block when YOKE_SKILL_CONTEXT=
# appears as a leading env var assignment in a command segment, not as a
# substring inside heredoc bodies, strings, grep patterns, or commit messages.
if "YOKE_SKILL_CONTEXT=" in command_stripped:
    _ctx_parts = re.split(r"[;&|\n]+|\$\(", command_stripped)
    for _cp in _ctx_parts:
        _cp = _cp.strip()
        if not _cp:
            continue
        _cw = _cp.split()
        if not _cw:
            continue
        # Check leading words for env var assignment pattern
        for _cword in _cw:
            if _cword.startswith("YOKE_SKILL_CONTEXT="):
                result = {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": (
                            "BLOCKED: Do not set YOKE_SKILL_CONTEXT manually. "
                            "This env var bypass was removed. "
                            "Use the skill layer (/yoke idea, /yoke advance, etc.) "
                            "which routes through the correct entry points."
                        ),
                    }
                }
                print(json.dumps(result))
                sys.exit(0)
            # Stop checking once we hit a non-assignment word (the command itself)
            if "=" not in _cword or _cword.startswith("="):
                break

"""
RULE_TEXT_GUARDS_CLI = r"""
# --- Check 5: Block claude CLI invocations ---
# Nested Claude Code sessions crash the parent process. Agents must use
# the Agent tool for subagent dispatch, never invoke claude as a CLI binary.
# Match "claude" as a standalone command (first word of a segment), but
# NOT references to .claude/ directory paths or the word in strings/comments.
if "claude" in command_stripped:
    from yoke_core.domain.lint_db_remote_claude import (
        REMOTE_CLAUDE_DENIAL,
        remote_claude_cli_state,
    )
    _remote_claude_seen, _remote_claude_allowed = remote_claude_cli_state(command_stripped, data)
    if _remote_claude_seen and not _remote_claude_allowed:
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": REMOTE_CLAUDE_DENIAL,
            }
        }
        print(json.dumps(result))
        sys.exit(0)
    # Split command on compound operators (&&, ||, ;, |) and subshells $()
    _segments = re.split(r"[;&|\n]+|\$\(", command_stripped)
    for _seg in _segments:
        _seg = _seg.strip()
        if not _seg:
            continue
        _words = _seg.split()
        if not _words:
            continue
        _first = _words[0]
        # Skip env var assignments preceding the command (e.g. VAR=val claude -p)
        _word_idx = 0
        while _word_idx < len(_words) and "=" in _words[_word_idx] and not _words[_word_idx].startswith("="):
            _word_idx += 1
        if _word_idx < len(_words):
            _first = _words[_word_idx]
        # Strip leading path to get basename
        _basename = _first.rsplit("/", 1)[-1] if "/" in _first else _first
        # Match exactly "claude" as the command binary
        if _basename == "claude":
            if _remote_claude_allowed:
                continue
            result = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        "BLOCKED: Do not invoke claude as a CLI command "
                        "— use the Agent tool for subagent dispatch. "
                        "Nested claude processes crash Claude Code sessions."
                    ),
                }
            }
            print(json.dumps(result))
            sys.exit(0)

"""
RULE_TEXT_BODY_BANS = r"""
# --- Check 13: Block ALL raw body writes ---
# items.body is renderer-owned. No raw body writes are supported.
# The mutation layer also rejects these, but lint provides the earlier error.
if (
    "items" in command_stripped and
    "update" in command_stripped and
    "body" in command_stripped and
    "--body-file" in command_stripped
):
    _body_write_pat = re.compile(
        r"yoke-db\.sh[" + chr(39) + r"\"]?\s+items\s+update\s+([^\s]+)\s+body\s+--body-file\b"
    )
    _body_match = _body_write_pat.search(command)
    if _body_match:
        _item_token = _body_match.group(1).strip(chr(34) + chr(39))
        _resolved_id = _item_token
        if _resolved_id.lower().startswith("yok-"):
            _resolved_id = _resolved_id[4:]
        _resolved_id = _resolved_id.lstrip("0") or "0"
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "BLOCKED: Raw body writes are no longer supported.\n"
                    "items.body is a rendered projection owned by the in-process render path.\n"
                    "Use: python3 -m yoke_core.cli.db_router items update %s <field> --body-file <path>\n"
                    "Valid structured fields: spec, design_spec, technical_plan, worktree_plan, shepherd_log, shepherd_caveats, test_results, deploy_log.\n"
                    "For supplemental sections: python3 -m yoke_core.domain.sections upsert <id> <name> --content-file <path>"
                ) % (_resolved_id,),
            }
        }
        print(json.dumps(result))
        sys.exit(0)

# --- Check 13b: Block ingest-body ---
# ingest-body is no longer supported. items.body is renderer-owned.
if "ingest-body" in command_stripped:
    _ingest_pat = re.compile(r"(?:yoke-db\.sh\s+items\s+ingest-body|backlog-registry\.sh\s+ingest-body)")
    if _ingest_pat.search(command_stripped):
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    "BLOCKED: ingest-body is no longer supported.\n"
                    "items.body is a rendered projection. .md files are generated views.\n"
                    "Use structured field writes instead: "
                    "python3 -m yoke_core.cli.db_router items update <id> spec --body-file <path>"
                ),
            }
        }
        print(json.dumps(result))
        sys.exit(0)

"""
