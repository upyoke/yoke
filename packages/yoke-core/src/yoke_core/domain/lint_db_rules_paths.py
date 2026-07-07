"""Path-resolution fragments for HOOK_POLICY_SOURCE."""

from __future__ import annotations


RULE_TEXT_WORKTREE_DB_PATH = r"""
# --- Check 0: Worktree-local Yoke DB path guessing ---
if "# lint:no-worktree-db-path-check" not in command_stripped:
    try:
        _db_path_tokens = shlex.split(original_command, posix=True)
    except Exception:
        _db_path_tokens = original_command.split()

    _worktree_db_re = re.compile(
        r"(?:^|/)\.worktrees/[^/\s]+/(?:data|yoke|runtime)/yoke\.db$"
    )
    _pwd_db_re = re.compile(
        r"^(?:\$PWD|\$\{PWD\}|\$\(pwd\)|`pwd`|"
        r"\$CLAUDE_PROJECT_DIR|\$\{CLAUDE_PROJECT_DIR\})/data/yoke\.db$"
    )
    for _db_tok in _db_path_tokens:
        _db_candidate = _db_tok.strip().rstrip(";,)]")
        if (
            "=" in _db_candidate
            and not _db_candidate.startswith(("/", ".", "$", "`"))
        ):
            _db_candidate = _db_candidate.split("=", 1)[1]
        if _worktree_db_re.search(_db_candidate) or _pwd_db_re.search(_db_candidate):
            result = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": (
                        "BLOCKED: Yoke control-plane DB paths are resolved, "
                        "never constructed. Do not use a worktree-local "
                        "`data/yoke.db` or `$PWD/data/yoke.db`. Use:\n"
                        "  python3 -m yoke_core.cli.db_router ...\n"
                        "  YOKE_PG_DSN / YOKE_PG_DSN_FILE for authority binding\n"
                        "Worktree-local DBs are validation surfaces only when "
                        "explicit env bindings surface them.\n"
                        "Suppression: # lint:no-worktree-db-path-check"
                    ),
                }
            }
            print(json.dumps(result))
            sys.exit(0)

"""

__all__ = ("RULE_TEXT_WORKTREE_DB_PATH",)
