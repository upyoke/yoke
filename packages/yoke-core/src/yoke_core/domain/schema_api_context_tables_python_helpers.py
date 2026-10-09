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
    "yoke_core.domain.project_identity": {
        "columns": [("render_item_ref", "callable")],
        "notes": (
            "Engine-owned connections render an internal items.id with "
            "render_item_ref(conn, item_id). The bulk renderer is "
            "item_ref_render.render_item_refs(conn, item_ids); there is no "
            "singular item_ref_render.render_item_ref. Client selectors "
            "carry the complete public PREFIX-N reference."
        ),
    },
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
            ("ActorContext", "pydantic.BaseModel"),
            ("TargetRef", "pydantic.BaseModel"),
            ("FunctionCallRequest", "pydantic.BaseModel"),
            ("FunctionCallResponse", "pydantic.BaseModel"),
        ],
        "notes": (
            "The exported actor model is `ActorContext`, not `ActorRef` "
            "(that guessed import does not exist). `TargetRef` names the target. "
            "`FunctionCallRequest.actor` requires `session_id`; `actor_id` "
            "is optional and resolves server-side from `harness_sessions` "
            "keyed on session_id. A supplied `actor_id` that disagrees "
            "with the resolved value is rejected with `actor_id_mismatch`. "
            "The dispatcher entrypoint is `yoke_function_dispatch.dispatch`; "
            "the HTTP route `POST /v1/functions/call` accepts the same "
            "envelope."
        ),
    },
    "runtime/harness/<harness-dir>/manifest.json": {
        "columns": [
            ("agent_wake", "object"),
            ("session_control", "object"),
            ("supports", "object"),
        ],
        "notes": (
            "Manifest directories are claude, codex, and cursor; executor "
            "claude-code resolves to claude, not a claude-code directory. "
            "The harness manifest is where harness capability truth lives — "
            "not any doc, skill, rules file, or agent body. Before stating "
            "what a harness can do, read the field: `agent_wake` answers "
            "whether it can be woken while idle and by which primitive "
            "(idle_wake / idle_wake_mechanism / timer_wake, each with the "
            "evidence behind it), `session_control` answers messaging and "
            "launch routes, `supports` answers hook affordances. Schema: "
            "runtime/harness/manifest-schema.md. Sources: "
            "yoke_contracts.harness_wake_capability and "
            "yoke_contracts.session_control; the manifests are rendered, so "
            "never hand-edit one. A capability nobody probed reads "
            "`unverified` — that is an answer, not a gap to fill by guessing."
        ),
    },
    "yoke_core.domain.db_helpers": {
        "columns": [
            ("instant_parameter", "callable"),
            ("iso8601_now", "callable"),
            ("connect", "callable"),
            ("query_rows", "callable"),
            ("query_one", "callable"),
            ("query_scalar", "callable"),
        ],
        "notes": (
            "Source-dev SQL and clock helpers. Agents use registered "
            "`yoke <subcommand>` surfaces for control-plane access. "
            "Native SQL writers import instant_parameter from this module; "
            "the wrong guess time_sql.instant_parameter does not exist. "
            "Parse ingress first: the adapter accepts aware datetime/null, "
            "binding natively on Postgres and fixed-six UTC/null on SQLite. "
            "There is NO `read_only=` keyword on `connect` and NO "
            "`get_canonical_conn` importable name on this module — those "
            "are wrong guesses the live denial log has captured. There is "
            "also NO `resolve_db_path` helper; that name was retired when "
            "DB authority moved to Postgres — call `connect()` with no "
            "path. The "
            "standalone FastAPI route-module connector is `connect`; importing "
            "`yoke_core.api.main.get_db_readonly` from a route module is a "
            "wrong guess because it re-enters app construction and creates a "
            "circular route import. The "
            "query helpers (`query_rows`, `query_one`, `query_scalar`) "
            "remain for compatibility while Postgres-native callers move "
            "through router-owned surfaces."
        ),
    },
    "yoke_core.domain.deployment_item_stamp": {
        "columns": [
            ("stamp_item_field", "callable"),
            ("transition_member_to_release", "callable"),
            ("STAMP_FUNCTION_ID", "const"),
        ],
        "notes": (
            "Pipeline member-item stamps (`deploy_stage`, `deployed_to`) go "
            "through `deployment_item_stamp.record` addressed by public "
            "`target.public_ref`. Do NOT call `items.scalar.update` (claim "
            "gate) or send a database integer as a client selector. The implemented→release flip "
            "uses `done_transition.item_status_set`, not `YOKE_CLAIM_BYPASS`."
        ),
    },
    "yoke_core.domain.json_helper": {
        "columns": [
            ("dumps_compact", "callable"),
            ("dumps_pretty", "callable"),
            ("loads_text", "callable"),
            ("load_path", "callable"),
            ("dump_path", "callable"),
        ],
        "notes": (
            "The encoder names carry their form: `dumps_compact` / "
            "`dumps_pretty` / `loads_text`. There is NO bare `dumps` or "
            "`loads` on this module — that wrong guess is in the failure "
            "log. A workflow definition is a separate case entirely: its "
            "stored text must be the exact bytes its digest hashes, so use "
            "`workflow_definition_codec.canonical_definition_json` with "
            "`definition_digest`, never a general-purpose encoder."
        ),
    },
    "yoke_contracts.model_reference": {
        "columns": [
            ("lookup_model_reference", "callable"),
            ("lookup_api_price", "callable"),
            ("validate_model_record", "callable"),
        ],
        "notes": (
            "Pure lookup helpers take records from a DB catalog revision. "
            "`lookup_model_reference` never raises; "
            "`researched=False` is unknown, not a gate. `lookup_api_price` "
            "returns None when unknown. `model_reference_revisions` stores "
            "effective-dated sourced catalogs; publish via `yoke models publish`. "
            "Records hold model facts only; level changes are proposed with "
            "`yoke models level-proposal` and stored by `yoke universe levels set`. "
            "Native availability is independent. CLI: `yoke models lookup MODEL_ID`. "
            "No `operator_preferences` field."
        ),
    },
    "yoke_core.domain.steering_fleet_report_deployment_runs": {
        "columns": [("run_progress", "callable")],
        "notes": (
            "Read live deployment run progress with run_progress(conn, "
            "project_id=..., now=...). Wrong guess: read_deployment_runs "
            "does not exist. Scoped QA reports include no_obligation_lines "
            "for carried members exempt under their own completion flow, and "
            "member_lines: one line per waiting item-QA member with its "
            "blocker count and whether its owner was woken (stage-wait notice "
            "or QA failure handoff)."
        ),
    },
}
