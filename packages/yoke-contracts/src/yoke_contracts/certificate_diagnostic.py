"""Shared certificate diagnostic authority."""

from __future__ import annotations

from yoke_contracts.https_retry_policy import certificate_validation_error
from yoke_contracts.json_error_safety import safe_diagnostic_text


def certificate_diagnostic(
    error: BaseException | None,
    *,
    sensitive_values: tuple[str, ...] = (),
) -> tuple[str, str] | None:
    """Report only the certificate facts the TLS verifier actually supplied."""
    certificate = certificate_validation_error(error)
    if certificate is None:
        return None
    reason = getattr(certificate, "verify_message", None) or str(certificate)
    detail = safe_diagnostic_text(
        f"certificate_validation_failed: {reason}", sensitive_values=sensitive_values
    )
    code = getattr(certificate, "verify_code", None)
    if code == 10:
        repair = "Renew the expired serving certificate and check the client clock."
    elif code in (62, 64):
        repair = "Correct the endpoint hostname or serve a certificate covering it."
    elif code in (18, 19, 20, 21):
        repair = (
            "Repair the server certificate chain or configure the client's trusted "
            "CA store with the intended certificate authority."
        )
    elif code == 9:
        repair = "Check the client clock and the certificate's validity start time."
    else:
        repair = (
            "Ask the endpoint operator to inspect the certificate and chain; "
            "check the client clock, hostname and trusted CA store."
        )
    return (
        detail,
        f"{repair} Retrying unchanged will not help. Keep TLS verification enabled.",
    )
