"""JSON-nested-field schemas surfaced inline in the agent-context packet.

Sibling of :mod:`schema_api_context_seed`. Several Yoke columns hold
JSON blobs whose nested-field shape is the actual schema agents need;
spelling those columns out as ``TEXT`` in the cheat sheet without naming
the inner fields is the friction class this module exists to kill.

Each entry maps a ``(table, column)`` pair to its nested-field
metadata: the inner field names + types + defaults, the validator
module that owns the canonical shape, and the access-pattern note that
keeps agents from raw-querying nested keys as top-level columns.

The packet renderer in :mod:`yoke_core.domain.schema_api_context`
groups entries by topic and emits one compact JSON-nested-field block
per topic under the schema cheat sheet.

Pure data only — no I/O, no DB connections, no imports beyond stdlib.
"""

from __future__ import annotations


# Access-pattern reminder repeated per entry — the renderer attaches it
# once per topic block, but keeping the canonical wording in one place
# means seed updates are not racing the renderer to phrase it the same
# way.
ACCESS_PATTERN_NOTE: str = (
    "parse the rendered JSON string; do NOT query nested fields as "
    "top-level columns"
)


# ``(table, column)`` -> nested-field metadata. Per spec: each block
# names nested field names + types + defaults + the validator module
# + the access-pattern note. ``topic`` keys the renderer's grouping;
# the renderer reads ``CANONICAL_TABLES`` to confirm the column exists.
JSON_NESTED_SCHEMAS: dict[tuple[str, str], dict] = {
    ("items", "browser_qa_metadata"): {
        "topic": "core",
        "validator": "yoke_core.domain.browser_qa_metadata.validate_json_string",
        "fields": [
            ("browser_testable", "bool", "false"),
            ("browser_routes", "list[str]", "[]"),
            ("browser_intents", "list[dict]", "[]"),
            ("browser_timing_budget_ms", "int", "0"),
        ],
    },
    ("items", "db_mutation_profile"): {
        "topic": "core",
        "validator": "yoke_core.domain.db_mutation_profile.validate_json_string",
        "fields": [
            ("state", "'none'|'declared'", "'none'"),
            ("model", "str|null", "null"),
            ("mutation_intent", "'apply'|'retire'", "null"),
            ("compatibility_class", "'pre_merge_safe'|'pre_merge_breaking'", "null"),
            ("migration_strategy", "'additive_only'|'hard_cutover'|'expand_contract'", "null"),
            ("migration_modules", "list[str]", "[]"),
        ],
    },
    ("items", "db_compatibility_attestation"): {
        "topic": "core",
        "validator": "yoke_core.domain.db_compatibility_attestation.validate_json_string",
        "fields": [
            ("pre_merge_readers_writers", "list[dict]", "[]"),
            ("invariants", "list[str]", "[]"),
            ("rehearsal_commands", "list[str]", "[]"),
            ("residual_risk_notes", "list[str]", "[]"),
            ("class_escalations", "list[dict]", "[]"),
            ("frozen_at", "str|null", "null"),
        ],
    },
    ("epic_tasks", "dependencies"): {
        "topic": "core",
        "validator": "yoke_core.domain.shepherd_dependency",
        "fields": [
            ("(JSON array of bare task_num integers within the same epic)", "list[int]", "[]"),
        ],
    },
    ("harness_sessions", "offer_envelope"): {
        "topic": "claims",
        "validator": "yoke_core.domain.sessions_offer_envelope_merge.merge_offer_envelope",
        "fields": [
            ("execution_lane", "str", "'primary'"),
            ("supported_paths", "list[str]", "[]"),
            ("capabilities", "list[str]", "[]"),
            ("workspace", "str", "''"),
            ("offered_at", "str (ISO-8601)", "''"),
        ],
    },
    ("qa_requirements", "capability_requirements"): {
        "topic": "qa",
        "validator": "yoke_core.domain.qa_requirement_ops",
        "fields": [
            ("(JSON array of capability tokens the executor must advertise)", "list[str]", "[]"),
        ],
    },
    ("qa_requirements", "success_policy"): {
        "topic": "qa",
        "validator": "yoke_core.domain.qa_requirement_ops",
        "fields": [
            ("kind", "'all_pass'|'any_pass'|'majority_pass'", "'all_pass'"),
            ("threshold", "int|null", "null"),
        ],
    },
}


__all__ = [
    "ACCESS_PATTERN_NOTE",
    "JSON_NESTED_SCHEMAS",
]
