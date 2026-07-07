"""Python helper surface entries for the schema cheat sheet.

Sibling of :mod:`schema_api_context_tables` (which combines per-topic
dicts into the canonical ``CANONICAL_TABLES``). Teaches the canonical
Python helper surface — the surfaces agents reach for inside a
``python3 -c "..."`` snippet — and explicitly names the wrong guesses
agents have made in the live denial / failure log.

These entries are not SQL tables — they live in the same per-topic
table map only because the renderer iterates ``TOPIC_TABLES`` for its
schema cheat sheet, and the same `name -> {columns, notes}` shape
works for "module surface" rows just as well. ``columns`` here lists
the public symbol surface (callable names or subcommand names) so the
renderer prints `module — sym1, sym2, ...` instead of an empty
backtick pair. ``_try_live_schema`` returns None for these "tables"
(no PRAGMA hit for a Python module name) so the seed entries pass
through to the renderer without drift triggering.

Pure data only — no I/O, no DB connections, no imports beyond stdlib.
"""

from __future__ import annotations


PYTHON_HELPERS_TABLES: dict[str, dict] = {
    "yoke_core.domain.worktree": {
        "columns": [
            ("paths db", "subcommand"),
            ("paths main", "subcommand"),
            ("paths yoke-root", "subcommand"),
            ("create", "subcommand"),
        ],
        "notes": (
            "Source-dev path resolver, not an agent-facing command. Agents "
            "should rely on registered `yoke ...` surfaces, explicit "
            "worktree paths from dispatch context, and git/worktree metadata "
            "instead of resolving Yoke control-plane authority through a "
            "path helper. The retired DB-path mode exists only as a refusal "
            "guard for stale SQLite recipes. Never import a guessed "
            "`get_db_path` helper; no such importable name exists."
        ),
    },
    "yoke_core.domain.sessions": {
        "columns": [
            ("register_session", "callable"),
            ("claim_work", "callable"),
            ("release_claim", "callable"),
            ("heartbeat", "callable"),
            ("end_session", "callable"),
        ],
        "notes": (
            "NO `get_active_session_id` / `get_current_session` importable "
            "name — that wrong guess is in the denial log. Current "
            "session id resolves ambiently (`$YOKE_SESSION_ID` fast "
            "path, then the hook-written process-anchor registry via "
            "`yoke_core.domain.session_ambient_identity`); actor id is "
            "`harness_sessions.actor_id` keyed by session_id. Prefer "
            "`yoke claims work acquire` / `yoke claims work release` "
            "over importing these callables directly."
        ),
    },
    "yoke_contracts.api.function_call": {
        "columns": [
            ("FunctionCallRequest", "pydantic.BaseModel"),
            ("FunctionCallResponse", "pydantic.BaseModel"),
        ],
        "notes": (
            "`FunctionCallRequest.actor` requires `session_id`; `actor_id` "
            "is optional and resolves server-side from `harness_sessions` "
            "keyed on session_id. A supplied `actor_id` that disagrees "
            "with the resolved value is rejected with `actor_id_mismatch`. "
            "The dispatcher entrypoint is `yoke_function_dispatch.dispatch`; "
            "the HTTP route `POST /v1/functions/call` accepts the same "
            "envelope."
        ),
    },
    "yoke_core.domain.db_helpers": {
        "columns": [
            ("iso8601_now", "callable"),
            ("resolve_db_path", "callable"),
            ("connect", "callable"),
            ("query_rows", "callable"),
            ("query_one", "callable"),
            ("query_scalar", "callable"),
        ],
        "notes": (
            "Legacy compatibility helper surface. Agents should prefer "
            "`python3 -m yoke_core.cli.db_router ...` or registered "
            "`yoke <subcommand>` surfaces for control-plane access. "
            "There is NO `read_only=` keyword on `connect` and NO "
            "`get_canonical_conn` importable name on this module — those "
            "are wrong guesses the live denial log has captured. The "
            "query helpers (`query_rows`, `query_one`, `query_scalar`) "
            "remain for compatibility while Postgres-native callers move "
            "through router-owned surfaces."
        ),
    },
}
