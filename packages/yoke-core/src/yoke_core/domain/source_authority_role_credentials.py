"""Secret-safe PostgreSQL role operations for source-authority cutover."""

from __future__ import annotations

import base64
import binascii
import hashlib
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
    """Prove the live role accepts only the cutover password verifier.

    This proof is evaluated through the already-authenticated cutover
    connection and never returns the stored verifier or either password.  It
    avoids depending on whether libpq reports SQLSTATE at connection time.
    """
    current_role = str(conn.execute("SELECT current_user").fetchone()[0])
    if current_role != bundle.admin_role:
        raise SourceCredentialError(
            "live cutover connection does not own the administrator role"
        )
    row = conn.execute(
        "SELECT rolpassword FROM pg_authid WHERE rolname=%s",
        (bundle.admin_role,),
    ).fetchone()
    if row is None or not row[0]:
        raise SourceCredentialError(
            "source administrator password verifier is unavailable"
        )
    verifier = str(row[0])
    original_matches = _password_matches_verifier(
        password_from_dsn(bundle.original_dsn), bundle.admin_role, verifier,
    )
    cutover_matches = _password_matches_verifier(
        password_from_dsn(bundle.cutover_dsn), bundle.admin_role, verifier,
    )
    if original_matches or not cutover_matches:
        raise SourceCredentialError(
            "live source password verifier does not prove credential rotation"
        )
    return verifier.split("$", 1)[0] if "$" in verifier else "md5"


def prove_role_retired(
    conn: object, bundle: SourceCredentialBundle,
) -> None:
    """Prove the committed role state through the still-live admin session."""
    row = conn.execute(
        "SELECT rolcanlogin, rolpassword FROM pg_authid WHERE rolname=%s",
        (bundle.admin_role,),
    ).fetchone()
    if row is None or bool(row[0]) or row[1] is not None:
        raise SourceCredentialError(
            "live source role does not prove permanent credential retirement"
        )


def _password_matches_verifier(password: str, role: str, verifier: str) -> bool:
    if verifier.startswith("md5") and len(verifier) == 35:
        digest = hashlib.md5(
            (password + role).encode("utf-8"), usedforsecurity=False,
        ).hexdigest()
        return hmac.compare_digest(verifier, "md5" + digest)
    if not verifier.startswith("SCRAM-SHA-256$"):
        raise SourceCredentialError(
            "source administrator password verifier format is unsupported"
        )
    try:
        _mechanism, parameters, keys = verifier.split("$", 2)
        iterations_text, salt_text = parameters.split(":", 1)
        stored_text, server_text = keys.split(":", 1)
        iterations = int(iterations_text)
        if iterations <= 0:
            raise ValueError
        salt = base64.b64decode(salt_text, validate=True)
        stored_key = base64.b64decode(stored_text, validate=True)
        server_key = base64.b64decode(server_text, validate=True)
        if not salt or len(stored_key) != 32 or len(server_key) != 32:
            raise ValueError
    except (ValueError, binascii.Error) as exc:
        raise SourceCredentialError(
            "source administrator password verifier is invalid"
        ) from exc
    salted = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations,
    )
    client_key = hmac.new(salted, b"Client Key", hashlib.sha256).digest()
    candidate = hashlib.sha256(client_key).digest()
    return hmac.compare_digest(candidate, stored_key)


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
