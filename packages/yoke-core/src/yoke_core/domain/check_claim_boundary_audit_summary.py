"""Full-ledger claim-boundary counts and bounded evidence, computed in SQL."""

from __future__ import annotations

import json
import re

from yoke_contracts.doctor_budget import CHECK_BUDGET_S, remaining_seconds
from yoke_core.domain import check_claim_boundary_audit_cutoff as cutoff
from yoke_core.domain.check_claim_boundary_audit_function_evidence import (
    _AUDITED_FUNCTION_FAMILIES,
    claimed_mutation_function_names,
    function_audit_metadata,
)
from yoke_core.domain.sql_json import json_text_expr, jsonb_text_expr
from yoke_core.domain.events_function_index import (
    FUNCTION_LOOKUP_CHARS,
    function_lookup_sql,
)
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.yoke_function_dispatch_claim_evidence import (
    CLAIM_VERIFICATION_ALLOWED,
    CLAIM_VERIFICATION_PHASE,
)


def _integer(expression: str) -> str:
    # Match Python's bare-integer coercion without risking a cast of a public ref.
    return (
        f"CASE WHEN ({expression}) ~ '^[+-]?[0-9]+$' THEN ({expression})::numeric END"
    )


_FINDINGS = {
    "YokeFunctionCalled": """
        SELECT id, subject AS item_id, caller, holder, surface, rationale,
               'function_call_attribution_mismatch'::text AS finding_class,
               CASE WHEN rationale IN (
                   'event caller differs from the pre-handler verified caller',
                   'pre-handler claim holder differs from the event caller',
                   'function call recorded under a session that did not hold the work claim at event time')
                   THEN 'FAIL' ELSE 'WARN' END AS severity
        FROM function_findings WHERE rationale IS NOT NULL
    """,
    "HarnessToolCallCompleted": """
        SELECT id, subject, caller, NULL, surface,
               'ambient HarnessToolCallCompleted returned a mutating function response but durable YokeFunctionCalled attribution is not correlated',
               'function_call_attribution_mismatch', 'WARN'
        FROM uncorrelated
    """,
    "ItemClaimReleaseOverride": f"""
        SELECT id, {_integer("item_id::text")}, caller, ctx ->> 'prior_owner_session_id',
               'ItemClaimReleaseOverride',
               CASE WHEN COALESCE(ctx ->> 'operator_rationale', '') !~ '\\S'
                    THEN 'override missing operator_rationale evidence'
                    ELSE 'cross-session claim release without operator-only attribution; caller differs from prior owner' END,
               'non_operator_claim_release_override',
               CASE WHEN COALESCE(ctx ->> 'operator_rationale', '') !~ '\\S' THEN 'WARN' ELSE 'FAIL' END
        FROM ledger WHERE event_name='ItemClaimReleaseOverride' AND (
            COALESCE(ctx ->> 'operator_rationale', '') !~ '\\S'
            OR (COALESCE(ctx ->> 'prior_owner_session_id', '') <> ''
                AND (ctx ->> 'prior_owner_session_id') IS DISTINCT FROM caller))
    """,
    "PathClaimAmended": """
        SELECT id, subject, caller, holder, surface,
               CASE WHEN COALESCE(caller, '')='' THEN 'caller session not recorded on the event — incomplete attribution evidence'
                    WHEN holder IS NULL THEN 'path-claim amendment recorded without any live work claim on the item — cannot verify ownership'
                    ELSE 'path-claim amendment recorded under a session that did not hold the live work claim at event time' END,
               'path_claim_mutation_without_owning_claim',
               CASE WHEN COALESCE(caller, '')='' OR holder IS NULL THEN 'WARN' ELSE 'FAIL' END
        FROM path_holders WHERE COALESCE(caller, '')='' OR holder IS NULL OR holder <> caller
    """,
}


def _query(path_owner: str, historical: str, event_name: str) -> str:
    item = (
        "COALESCE("
        + ", ".join(
            _integer(e)
            for e in (
                "ctx #>> '{target,item_id}'",
                "ctx #>> '{claim_verification,target_item_id}'",
                "CASE WHEN kind='epic' THEN ctx #>> '{target,epic_id}' END",
                "CASE WHEN kind='epic' THEN ctx #>> '{claim_verification,target_epic_id}' END",
                "item_id::text",
            )
        )
        + ")"
    )
    durable_item = (
        "COALESCE("
        + _integer(f"{jsonb_text_expr('d.envelope')} #>> '{{context,target,item_id}}'")
        + ", "
        + _integer("d.item_id::text")
        + ")"
    )
    claim_scope = "translate(jsonb_build_object('item_id', subject)::text, ' ', '')"
    # Separate LIKE clauses expose each family prefix to text_pattern_ops.
    # The same decoded expression indexes encoded keys and values correctly.
    if any(
        len(family) >= FUNCTION_LOOKUP_CHARS for family in _AUDITED_FUNCTION_FAMILIES
    ):
        raise RuntimeError("audit_function_family_exceeds_index_prefix")
    identity = function_lookup_sql()
    candidates = " OR ".join(
        [f"{identity}=ANY(%(families)s)"]
        + [
            f"{identity} LIKE %(function_family_{i})s"
            for i in range(len(_AUDITED_FUNCTION_FAMILIES))
        ]
    )
    function_filter = (
        f"AND ({candidates})" if event_name == "YokeFunctionCalled" else ""
    )
    sql = f"""
    WITH metadata AS MATERIALIZED (
        SELECT key AS function, value #>> '{{kind}}' AS kind
        FROM jsonb_each(%(metadata)s::jsonb)
    ), ledger AS NOT MATERIALIZED (
        SELECT id, session_id AS caller, item_id, created_at, event_name,
               anomaly_flags, fields.function AS function_id, fields.side_effects AS side_effects,
               fields.claim_required_kind AS declared_kind,
               ({json_text_expr("envelope")} #> '{{context,claim_required_kind}}') IS NOT NULL AS has_declared_kind,
               fields.target AS target, fields.claim_verification AS verification_snapshot,
               jsonb_build_object('function', fields.function, 'side_effects', fields.side_effects,
                   'target', fields.target, 'claim_verification', fields.claim_verification,
                   'detail', jsonb_build_object('tool_response_preview', fields.detail ->> 'tool_response_preview'),
                   'prior_owner_session_id', fields.prior_owner_session_id,
                   'operator_rationale', fields.operator_rationale, 'claim_id', fields.claim_id)
               || CASE WHEN ({json_text_expr("envelope")} #> '{{context,claim_required_kind}}') IS NOT NULL
                       THEN jsonb_build_object('claim_required_kind', fields.claim_required_kind)
                       ELSE '{{}}'::jsonb END AS ctx
        FROM events
        CROSS JOIN LATERAL json_to_record(
            CASE WHEN json_typeof({json_text_expr("envelope")} -> 'context')='object'
                 THEN {json_text_expr("envelope")} -> 'context' ELSE '{{}}'::json END
        ) fields(function text, side_effects jsonb, target jsonb, claim_verification jsonb,
                 detail json, prior_owner_session_id text, operator_rationale text,
                 claim_id text, claim_required_kind json)
        WHERE id >= %(cutoff)s AND event_name = %(event_name)s
          {function_filter}
          AND (event_name <> 'HarnessToolCallCompleted'
               OR (anomaly_flags LIKE %(unattributed)s AND envelope ~ %(candidate_pattern)s))
    ), function_metadata AS MATERIALIZED (
        SELECT e.id, e.caller, e.item_id, e.created_at,
               jsonb_build_object('target', e.target,
                                  'claim_verification', e.verification_snapshot) AS ctx,
               e.function_id AS surface,
               CASE WHEN e.has_declared_kind THEN e.declared_kind::jsonb #>> '{{}}'
                    ELSE m.kind END AS kind,
               CASE WHEN jsonb_typeof(e.side_effects)='array'
                    THEN EXISTS (SELECT 1 FROM jsonb_array_elements(e.side_effects) effect
                                 WHERE effect NOT IN ('null'::jsonb, '\"\"'::jsonb, 'false'::jsonb, '0'::jsonb, '[]'::jsonb, '{{}}'::jsonb))
                    ELSE m.function IS NOT NULL END AS mutates
        FROM ledger e LEFT JOIN metadata m ON m.function=e.function_id
        WHERE event_name='YokeFunctionCalled'
          AND (e.function_id=ANY(%(families)s) OR e.function_id LIKE ANY(%(prefixes)s))
    ), function_targets AS MATERIALIZED (
        SELECT *, {item} AS subject,
               ctx #> '{{claim_verification}}' AS verification
        FROM function_metadata WHERE mutates AND kind IN ('item', 'epic', 'qa_subject')
    ), function_holders AS MATERIALIZED (
        SELECT *, CASE WHEN verification ->> 'phase'=%(snapshot_phase)s
            THEN NULLIF(verification ->> 'holder_session_id', '')
            ELSE (SELECT w.session_id FROM work_claims w
                  WHERE w.target_kind='item' AND w.scope={claim_scope}
                    AND w.claimed_at <= f.created_at
                    AND (w.released_at IS NULL OR w.released_at >= f.created_at)
                  ORDER BY w.claimed_at DESC LIMIT 1) END AS holder
        FROM function_targets f WHERE subject IS NOT NULL
    ), function_findings AS (
        SELECT *, CASE WHEN verification ->> 'phase'=%(snapshot_phase)s THEN
            CASE
                WHEN (verification ->> 'required_kind') IS DISTINCT FROM kind
                    THEN 'pre-handler claim evidence disagrees with function metadata'
                WHEN (verification ->> 'decision') IS DISTINCT FROM %(snapshot_allowed)s
                    THEN 'pre-handler evidence does not record an allowed claim decision'
                WHEN COALESCE(caller, '')='' THEN 'caller session not recorded on the event'
                WHEN NULLIF(verification ->> 'caller_session_id', '') IS DISTINCT FROM caller
                    THEN 'event caller differs from the pre-handler verified caller'
                WHEN kind IN ('item', 'epic') AND holder IS NULL
                    THEN 'pre-handler evidence is missing the verified claim holder'
                WHEN holder IS NOT NULL AND holder <> caller
                    THEN 'pre-handler claim holder differs from the event caller'
            END ELSE CASE
                WHEN COALESCE(caller, '')='' THEN 'caller session not recorded on the event — incomplete attribution evidence'
                WHEN holder IS NULL THEN 'no live work claim recorded at event time — cannot verify authorisation'
                WHEN holder <> caller THEN 'function call recorded under a session that did not hold the work claim at event time'
            END END AS rationale
        FROM function_holders
    ), harness_previews AS (
        SELECT e.*, ctx #>> '{{detail,tool_response_preview}}' AS preview
        FROM ledger e WHERE event_name='HarnessToolCallCompleted'
          AND anomaly_flags LIKE %(unattributed)s
          AND ctx #>> '{{detail,tool_response_preview}}' ~ %(candidate_pattern)s
    ), harness_responses AS MATERIALIZED (
        SELECT h.id, h.caller, h.item_id, response FROM harness_previews h
        CROSS JOIN LATERAL (
            SELECT CASE WHEN h.preview IS JSON OBJECT AND
                CASE WHEN h.preview IS JSON OBJECT THEN h.preview::jsonb -> 'success' END='true'::jsonb
                THEN h.preview::jsonb ELSE (
                SELECT candidate::jsonb FROM (
                    SELECT left(start_text.text, ending.endpos) AS candidate, starts.start, ending.endpos
                    FROM (
                        SELECT line, COALESCE(sum(length(line)+1) OVER (
                            ORDER BY n ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0)::int+1 AS start
                        FROM regexp_split_to_table(h.preview, E'\\n') WITH ORDINALITY lines(line, n)
                    ) starts
                    CROSS JOIN LATERAL (
                        SELECT ltrim(substring(h.preview FROM starts.start), E' \\t\\r\\n') AS text
                    ) start_text
                    CROSS JOIN LATERAL (
                        SELECT sum(length(parts[1])) OVER (ORDER BY n)::int AS endpos
                        FROM regexp_matches(start_text.text, '[^}}]*[}}]', 'g')
                            WITH ORDINALITY ends(parts, n)
                    ) ending
                    WHERE starts.line ~ '^[ \\t\\r]*\\{{'
                ) candidates
                WHERE candidate IS JSON OBJECT
                  AND CASE WHEN candidate IS JSON OBJECT THEN candidate::jsonb -> 'success' END='true'::jsonb
                ORDER BY start, endpos LIMIT 1
            ) END AS response
        ) parsed
    ), harness_targets AS (
        SELECT h.*, response ->> 'function' AS surface,
               COALESCE({_integer("response #>> '{result,item_id}'")}, {_integer("item_id::text")}) AS subject
        FROM harness_responses h JOIN metadata m ON m.function=response ->> 'function'
        WHERE response -> 'success'='true'::jsonb
    ), uncorrelated AS (
        SELECT h.* FROM harness_targets h WHERE NOT EXISTS (
            SELECT 1 FROM (
                SELECT session_id, item_id, envelope, event_name FROM events
                WHERE id BETWEEN h.id-50 AND h.id+50 OFFSET 0
              ) d WHERE d.event_name='YokeFunctionCalled' AND d.session_id=h.caller
              AND {jsonb_text_expr("d.envelope")} #>> '{{context,function}}'=h.surface
              AND {durable_item}=h.subject
        )
    ), path_holders AS (
        SELECT e.*, {_integer("item_id::text")} AS subject, 'PathClaimAmended'::text AS surface,
               (SELECT w.session_id FROM work_claims w
                WHERE w.target_kind='item' AND w.scope=translate(jsonb_build_object('item_id', {_integer("e.item_id::text")})::text, ' ', '')
                  AND w.claimed_at <= e.created_at
                  AND (w.released_at IS NULL OR w.released_at >= e.created_at)
                ORDER BY w.claimed_at DESC LIMIT 1) AS holder
        FROM ledger e WHERE event_name='PathClaimAmended' AND {_integer("item_id::text")} IS NOT NULL
          AND NOT ({path_owner})
    ), findings(id, item_id, caller, holder, surface, rationale, finding_class, severity) AS (
        {_FINDINGS[event_name]}
    ), annotated AS (
        SELECT f.*, ({historical}) AS historical FROM findings f
    ), ranked AS (
        SELECT *, row_number() OVER (ORDER BY severity, historical, id) AS preview_rank FROM annotated
    )
    SELECT COUNT(*) FILTER (WHERE severity='FAIL'), COUNT(*) FILTER (WHERE severity='WARN'),
           COALESCE(jsonb_agg(to_jsonb(ranked)-'preview_rank') FILTER (WHERE preview_rank <= %(preview_limit)s), '[]'::jsonb)
    FROM ranked
    """
    boundaries = [
        sql.index("    ), " + name)
        for name in (
            "function_metadata AS",
            "harness_previews AS",
            "path_holders AS",
            "findings(",
        )
    ]
    head = sql[: boundaries[0]]
    groups = {
        "YokeFunctionCalled": sql[boundaries[0] : boundaries[1]],
        "HarnessToolCallCompleted": sql[boundaries[1] : boundaries[2]],
        "PathClaimAmended": sql[boundaries[2] : boundaries[3]],
    }
    return head + groups.get(event_name, "") + sql[boundaries[3] :]


def audit_summary(conn, *, preview_limit: int = 10) -> tuple[int, int, list]:
    """Aggregate all eligible history, retaining the explicit residue cutoff."""
    remaining_seconds(CHECK_BUDGET_S)
    metadata = {
        name: {"kind": function_audit_metadata({}, name).claim_required_kind}
        for name in claimed_mutation_function_names()
    }
    claim_id = _integer("e.ctx ->> 'claim_id'")
    path_owner = "FALSE"
    if (
        _table_exists(conn, "path_claims")
        and _column_exists(conn, "path_claims", "owner_kind")
        and _column_exists(conn, "path_claims", "owner_item_id")
    ):
        path_owner = (
            "EXISTS (SELECT 1 FROM path_claims p WHERE p.owner_kind='item' "
            f"AND p.id={claim_id} "
            f"AND p.owner_item_id={_integer('e.item_id::text')})"
        )
    historical = "FALSE"
    if _table_exists(conn, "items"):
        historical = (
            "f.severity='WARN' AND f.holder IS NULL AND EXISTS "
            "(SELECT 1 FROM items i WHERE i.id=CASE WHEN abs(f.item_id) < 9223372036854775808 THEN f.item_id::bigint END AND lower(i.status)='done')"
        )
    family_pattern = (
        "(" + "|".join(re.escape(family) for family in _AUDITED_FUNCTION_FAMILIES) + ")"
    )
    # Only encoded identifier characters need a fallback; escaped ANSI/control
    # bytes in unrelated payloads do not turn those rows into audit candidates.
    encoded_ascii = (
        r"\\u00(?:2[eE]|3[0-9]|4[1-9a-fA-F]|5[0-9aAfF]|6[1-9a-fA-F]|7[0-9aA])"
    )
    candidate_pattern = family_pattern + "|" + encoded_ascii
    fails = warns = 0
    preview = []
    # Separate aggregates let PostgreSQL parallelize the large function ledger;
    # preview-parser correlations otherwise make the entire shared scan serial.
    for event_name in _FINDINGS:
        remaining_seconds(CHECK_BUDGET_S)
        row = conn.execute(
            _query(path_owner, historical, event_name),
            {
                "metadata": json.dumps(metadata),
                "cutoff": cutoff.read_min_event_id_cutoff(),
                "event_name": event_name,
                **{
                    f"function_family_{i}": family.replace("_", "\\_") + ".%"
                    for i, family in enumerate(_AUDITED_FUNCTION_FAMILIES)
                },
                "unattributed": "%unattributed%",
                "candidate_pattern": candidate_pattern,
                "families": list(_AUDITED_FUNCTION_FAMILIES),
                "prefixes": [
                    family.replace("_", "\\_") + ".%"
                    for family in _AUDITED_FUNCTION_FAMILIES
                ],
                "snapshot_phase": CLAIM_VERIFICATION_PHASE,
                "snapshot_allowed": CLAIM_VERIFICATION_ALLOWED,
                "preview_limit": preview_limit,
            },
        ).fetchone()
        fails += int(row[0])
        warns += int(row[1])
        preview.extend(row[2])
    remaining_seconds(CHECK_BUDGET_S)
    preview.sort(key=lambda f: (f["severity"], f["historical"], f["id"]))
    return fails, warns, preview[:preview_limit]
