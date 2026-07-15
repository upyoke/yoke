"""Secret-safe PostgreSQL role operations for source-authority cutover."""

from __future__ import annotations

import hmac

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


def prove_role_password_rotation(
    conn: object, bundle: SourceCredentialBundle,
) -> str:
    """Prove the committed rotation through the fresh cutover connection.

    ``begin`` connects with the original credential before ``ALTER ROLE``,
    commits the replacement with the fence, closes that session, and calls
    this function only through a new connection made with ``cutover_dsn``.
    PostgreSQL stores one password verifier per role, and the owner-only bundle
    requires the generated replacement to differ from the original.  Those
    facts prove supersession without reading provider-restricted ``pg_authid``
    or accepting connection-error text as evidence.
    """
    current_role = str(conn.execute("SELECT current_user").fetchone()[0])
    if current_role != bundle.admin_role:
        raise SourceCredentialError(
            "live cutover connection does not own the administrator role"
        )
    original_password = password_from_dsn(bundle.original_dsn)
    cutover_password = password_from_dsn(bundle.cutover_dsn)
    if hmac.compare_digest(original_password, cutover_password):
        raise SourceCredentialError(
            "cutover credential does not supersede the original credential"
        )
    return "postgres-single-verifier-cutover-reconnect"


def prove_role_retired(
    conn: object, bundle: SourceCredentialBundle,
) -> dict[str, object]:
    """Prove committed retirement through the still-live catalog authority.

    Connection-time authentication errors are reported differently across
    libpq builds.  The authenticated session instead reads the authoritative
    role catalog after commit, without returning password-verifier material.
    """
    row = conn.execute(
        "SELECT rolcanlogin, rolpassword FROM pg_authid WHERE rolname=%s",
        (bundle.admin_role,),
    ).fetchone()
    if row is None or bool(row[0]) or row[1] is not None:
        raise SourceCredentialError(
            "live source role does not prove permanent credential retirement"
        )
    return {
        "method": "live-role-catalog-state",
        "login_disabled": True,
        "password_cleared": True,
    }


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
    "prove_role_password_rotation", "prove_role_retired",
    "restore_role_credential",
    "retire_role_credential", "role_login_state", "rotate_role_password",
]
