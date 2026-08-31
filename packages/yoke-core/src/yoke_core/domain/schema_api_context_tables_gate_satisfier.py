"""``core`` topic table entries for the gate-satisfier substrate.

Sibling of :mod:`schema_api_context_tables` (which combines per-topic
dicts into the canonical ``CANONICAL_TABLES``). Holds the two tables
that carry gate satisfier ladders: ``item_gate_satisfactions`` and
``project_derived_facts``.

Pure data only — no I/O, no DB connections, no imports beyond stdlib.
"""

from __future__ import annotations


GATE_SATISFIER_TABLES: dict[str, dict] = {
    "item_gate_satisfactions": {
        "columns": [
            ("id", "INTEGER"),
            ("item_id", "INTEGER"),
            ("obligation", "TEXT"),
            ("rung_id", "TEXT"),
            ("target_status", "TEXT"),
            ("detail", "TEXT"),
            ("facts", "TEXT"),
            ("recorded_at", "TEXT"),
            ("recorded_by_session_id", "TEXT"),
        ],
        "notes": (
            "One row per (item_id, obligation) recording WHICH rung of that "
            "obligation's satisfier ladder actually discharged it — the "
            "durable answer to 'was this done merged with CI, merged "
            "locally, or merely attested'. Live obligations: "
            "'path_claim_boundary' (rungs remote_integration_ref, "
            "local_integration_ref), 'done_merge_evidence' (merged_with_ci, "
            "merged_locally, agent_attested), 'delivery_evidence' "
            "(deployment_run_succeeded, merge_only), and 'integration_trunk' "
            "(declared_default_branch, derived_default_branch). `facts` is a "
            "JSON `{fact_key: present|absent|unknown}` snapshot of what the "
            "ladder resolved against. Rows are upserted, not appended: "
            "re-satisfying an obligation replaces its row. Read them from "
            "item detail's `gate_satisfactions` key or with "
            "`yoke_core.domain.gate_satisfier_stamp.read_rungs`; writes go "
            "through the internal `gate_satisfier.rung.resolve` function "
            "(wrong guess — there is no `item_gate_rungs` table and no "
            "agent-facing CLI adapter for the resolve call)."
        ),
    },
    "project_derived_facts": {
        "columns": [
            ("id", "INTEGER"),
            ("project_id", "INTEGER"),
            ("fact_key", "TEXT"),
            ("present", "INTEGER"),
            ("fact_value", "TEXT"),
            ("observed_at", "TEXT"),
            ("observed_from", "TEXT"),
        ],
        "notes": (
            "Project truth nobody declared but the control plane can observe "
            "about itself, converged on every `project.snapshot.sync` the way "
            "path-context rows are. Live `fact_key` values: 'remote_present', "
            "'default_branch', 'test_command_declared', "
            "'environments_present'. Ladders read these under the `derived:` "
            "prefix (e.g. `derived:default_branch`), alongside `declared:` "
            "capability rows, `item:` per-item control-plane observations, "
            "and `observed:` facts the calling machine probes. A MISSING row "
            "reads as UNKNOWN, never as false — the ladder refuses and names "
            "`yoke project snapshot sync` as the recovery."
        ),
    },
}


__all__ = ["GATE_SATISFIER_TABLES"]
