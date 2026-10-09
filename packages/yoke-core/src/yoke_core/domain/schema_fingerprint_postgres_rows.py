"""Canonical PostgreSQL catalog rows for schema fingerprint comparison."""

from __future__ import annotations


def _postgres_schema_rows(
    conn,
    *,
    order_table_columns_by_name: bool = False,
) -> list[tuple[str, str, str]]:
    """Canonical Postgres schema rows for exact or name-mapped comparison."""
    table_column_order = (
        'att.attname COLLATE "C"' if order_table_columns_by_name else "att.attnum"
    )
    query = """
        WITH objects AS (
            SELECT
                'table' AS object_type,
                cls.relname AS object_name,
                cls.relkind::text || ':' || cls.relpersistence::text || ':' ||
                COALESCE(am.amname, '') || ':' ||
                cls.relrowsecurity::text || ':' ||
                cls.relforcerowsecurity::text || ':' ||
                COALESCE(
                    (
                        SELECT string_agg(option, ',' ORDER BY option)
                        FROM unnest(cls.reloptions) AS option
                    ),
                    ''
                ) || chr(10) ||
                string_agg(
                    att.attname || ':' ||
                    pg_catalog.format_type(att.atttypid, att.atttypmod) || ':' ||
                    COALESCE(
                        CASE WHEN att.attcollation = 0 THEN '' ELSE
                            coll_ns.nspname || '.' || coll.collname
                        END,
                        ''
                    ) || ':' ||
                    COALESCE(
                        pg_catalog.pg_get_expr(def.adbin, def.adrelid),
                        ''
                    ) || ':' ||
                    CASE WHEN att.attnotnull THEN 'NO' ELSE 'YES' END || ':' ||
                    att.attidentity::text || ':' || att.attgenerated::text || ':' ||
                    COALESCE(
                        pg_catalog.pg_get_serial_sequence(
                            pg_catalog.quote_ident(ns.nspname) || '.' ||
                                pg_catalog.quote_ident(cls.relname),
                            att.attname
                        ),
                        ''
                    ),
                    chr(10) ORDER BY __TABLE_COLUMN_ORDER__
                ) AS definition
            FROM pg_catalog.pg_class cls
            JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace
            JOIN pg_catalog.pg_attribute att ON att.attrelid = cls.oid
            LEFT JOIN pg_catalog.pg_am am ON am.oid = cls.relam
            LEFT JOIN pg_catalog.pg_collation coll ON coll.oid = att.attcollation
            LEFT JOIN pg_catalog.pg_namespace coll_ns ON coll_ns.oid = coll.collnamespace
            LEFT JOIN pg_catalog.pg_attrdef def
              ON def.adrelid = att.attrelid AND def.adnum = att.attnum
            WHERE ns.nspname = current_schema()
              AND cls.relkind IN ('r', 'p')
              AND att.attnum > 0
              AND NOT att.attisdropped
            GROUP BY cls.oid, cls.relname, am.amname

            UNION ALL

            SELECT
                'sequence' AS object_type,
                cls.relname AS object_name,
                pg_catalog.format_type(seq.seqtypid, NULL) || ':' ||
                    seq.seqstart || ':' || seq.seqincrement || ':' ||
                    seq.seqmax || ':' || seq.seqmin || ':' ||
                    seq.seqcache || ':' || seq.seqcycle AS definition
            FROM pg_catalog.pg_sequence seq
            JOIN pg_catalog.pg_class cls ON cls.oid = seq.seqrelid
            JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace
            WHERE ns.nspname = current_schema()

            UNION ALL

            SELECT
                'view' AS object_type,
                cls.relname AS object_name,
                COALESCE(
                    (
                        SELECT string_agg(option, ',' ORDER BY option)
                        FROM unnest(cls.reloptions) AS option
                    ),
                    ''
                ) || chr(10) ||
                COALESCE(pg_catalog.pg_get_viewdef(cls.oid, true), '') AS definition
            FROM pg_catalog.pg_class cls
            JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace
            WHERE ns.nspname = current_schema()
              AND cls.relkind IN ('v', 'm')

            UNION ALL

            SELECT
                'function' AS object_type,
                proc.proname || '(' ||
                    pg_catalog.pg_get_function_identity_arguments(proc.oid) || ')'
                    AS object_name,
                pg_catalog.pg_get_functiondef(proc.oid) AS definition
            FROM pg_catalog.pg_proc proc
            JOIN pg_catalog.pg_namespace ns ON ns.oid = proc.pronamespace
            WHERE ns.nspname = current_schema()
              AND proc.prokind IN ('f', 'p')

            UNION ALL

            SELECT
                'trigger' AS object_type,
                cls.relname || '.' || trig.tgname AS object_name,
                trig.tgenabled::text || ':' ||
                    pg_catalog.pg_get_triggerdef(trig.oid, true) AS definition
            FROM pg_catalog.pg_trigger trig
            JOIN pg_catalog.pg_class cls ON cls.oid = trig.tgrelid
            JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace
            WHERE ns.nspname = current_schema()
              AND NOT trig.tgisinternal

            UNION ALL

            SELECT
                'rule' AS object_type,
                cls.relname || '.' || rewrite.rulename AS object_name,
                pg_catalog.pg_get_ruledef(rewrite.oid, true) AS definition
            FROM pg_catalog.pg_rewrite rewrite
            JOIN pg_catalog.pg_class cls ON cls.oid = rewrite.ev_class
            JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace
            WHERE ns.nspname = current_schema()
              AND rewrite.rulename <> '_RETURN'

            UNION ALL

            SELECT
                'policy' AS object_type,
                cls.relname || '.' || policy.polname AS object_name,
                policy.polcmd::text || ':' || policy.polpermissive::text || ':' ||
                    COALESCE(
                        (
                            SELECT string_agg(
                                CASE WHEN role_oid = 0 THEN 'PUBLIC'
                                    ELSE pg_catalog.pg_get_userbyid(role_oid)
                                END,
                                ',' ORDER BY role_oid
                            )
                            FROM unnest(policy.polroles) AS role_oid
                        ),
                        ''
                    ) || ':' ||
                    COALESCE(pg_catalog.pg_get_expr(policy.polqual, policy.polrelid), '') || ':' ||
                    COALESCE(pg_catalog.pg_get_expr(policy.polwithcheck, policy.polrelid), '')
                    AS definition
            FROM pg_catalog.pg_policy policy
            JOIN pg_catalog.pg_class cls ON cls.oid = policy.polrelid
            JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace
            WHERE ns.nspname = current_schema()

            UNION ALL

            SELECT
                'index' AS object_type,
                idx.relname AS object_name,
                ind.indisvalid::text || ':' || ind.indisready::text || ':' ||
                    ind.indislive::text || ':' || ind.indcheckxmin::text || ':' ||
                    ind.indisreplident::text || ':' ||
                    pg_catalog.pg_get_indexdef(idx.oid) AS definition
            FROM pg_catalog.pg_index ind
            JOIN pg_catalog.pg_class idx ON idx.oid = ind.indexrelid
            JOIN pg_catalog.pg_class tbl ON tbl.oid = ind.indrelid
            JOIN pg_catalog.pg_namespace ns ON ns.oid = tbl.relnamespace
            WHERE ns.nspname = current_schema()

            UNION ALL

            SELECT
                'constraint' AS object_type,
                con.conname AS object_name,
                cls.relname || ':' ||
                    con.convalidated::text || ':' ||
                    con.condeferrable::text || ':' ||
                    con.condeferred::text || ':' ||
                    pg_catalog.pg_get_constraintdef(con.oid) AS definition
            FROM pg_catalog.pg_constraint con
            JOIN pg_catalog.pg_class cls ON cls.oid = con.conrelid
            JOIN pg_catalog.pg_namespace ns ON ns.oid = cls.relnamespace
            WHERE ns.nspname = current_schema()
        )
        SELECT object_type, object_name, COALESCE(definition, '')
        FROM objects
        ORDER BY object_type, object_name, definition
        """.replace("__TABLE_COLUMN_ORDER__", table_column_order)
    rows = conn.execute(query).fetchall()
    return [tuple(str(value) for value in row) for row in rows]
