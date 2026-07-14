"""Secret-safe PostgreSQL role operations for source-authority cutover."""

from __future__ import annotations

from psycopg import sql

from yoke_core.domain.source_authority_credentials import (
    SourceCredentialBundle,
    SourceCredentialError,
    password_from_dsn,
)


def role_login_state(conn: object, role: str) -> bool:
    row = conn.execute(
        "SELECT rolcanlogin FROM pg_roles WHERE rolname=%s", (role,),
    ).fetchone()
    if row is None:
        raise SourceCredentialError("source administrator role is missing")
    return bool(row[0])


def rotate_role_password(conn: object, bundle: SourceCredentialBundle) -> None:
    _set_role_credential(
        conn, role=bundle.admin_role,
        password=password_from_dsn(bundle.cutover_dsn), login=True,
    )


def restore_role_credential(conn: object, bundle: SourceCredentialBundle) -> None:
    _set_role_credential(
        conn, role=bundle.admin_role,
        password=password_from_dsn(bundle.original_dsn),
        login=bundle.original_rolcanlogin,
    )


def retire_role_credential(conn: object, bundle: SourceCredentialBundle) -> None:
    conn.execute(sql.SQL("ALTER ROLE {} NOLOGIN PASSWORD NULL").format(
        sql.Identifier(bundle.admin_role),
    ))


def _set_role_credential(
    conn: object, *, role: str, password: str, login: bool,
) -> None:
    """Alter a role while password material travels only as a bound value.

    PostgreSQL utility statements don't accept extended-protocol parameters
    for ``ALTER ROLE ... PASSWORD``. A transaction-local helper receives the
    secret as a function argument and constructs the utility statement inside
    PostgreSQL. Client-visible statements and errors contain placeholders.
    """
    conn.execute(
        """
        CREATE OR REPLACE FUNCTION pg_temp.yoke_set_role_credential(
            selected_role name, selected_password text, selected_login boolean
        ) RETURNS void LANGUAGE plpgsql AS $function$
        BEGIN
            EXECUTE format(
                'ALTER ROLE %I %s PASSWORD %L',
                selected_role,
                CASE WHEN selected_login THEN 'LOGIN' ELSE 'NOLOGIN' END,
                selected_password
            );
        EXCEPTION WHEN OTHERS THEN
            RAISE EXCEPTION 'source administrator credential update failed';
        END
        $function$
        """
    )
    conn.execute(
        "SELECT pg_temp.yoke_set_role_credential(%s, %s, %s)",
        (role, password, login),
    )


__all__ = [
    "restore_role_credential", "retire_role_credential", "role_login_state",
    "rotate_role_password",
]
