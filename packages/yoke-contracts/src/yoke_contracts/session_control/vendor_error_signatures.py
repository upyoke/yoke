"""The one list of vendor failures a turn can end on, and what each means.

A turn that ends on the model provider's side ends for a small number of
distinguishable reasons, and the reason decides what the control plane
should do next. "The server is busy" is worth retrying in a minute. "This
client build is no longer served" is worth retrying too, because the
binary can be replaced underneath a running fleet — that is exactly what
happened on 2026-09-03, when five workers died on an upstream 404 and the
desktop app's own auto-update fixed it twenty minutes later. "You are out
of quota until the window resets" is worth no retry at all: attempts
against a wall only spend the budget that a genuinely transient failure
would need.

Those are three different answers, and the whole point of this module is
that they are read off one list rather than re-decided at each call site.
A vendor message is a string that changes without notice, so every reader
that pattern-matches one for itself is a place the next wording silently
stops matching. Adding a newly observed failure means adding one entry
here.

Matching is deliberately two-sided. The vendor's own classification code
is the better signal when it is specific, but it is frequently not: the
live 404 arrived as ``codex_error_info: "other"``, which names nothing, so
the message text was the only thing that identified it. So an entry may
match on either, and an unrecognized failure resolves to
:data:`UNCLASSIFIED_VENDOR_ERROR` rather than to nothing — a turn that
demonstrably died on the vendor is still a turn to recover, and reporting
the raw message unclassified is how the next signature gets written.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VendorErrorSignature:
    """One recognizable way a provider ends a turn, and the response to it."""

    #: Stable id. Recorded on events and rendered on the fleet report, so
    #: it is the string an operator greps for and must not be reworded.
    signature_id: str
    #: Whether re-running the same turn can succeed without anyone acting.
    #: ``False`` is not "give up" — it is "no attempt can help, so name the
    #: person who can", and the report row says which.
    retryable: bool
    #: One line an operator reads on the report, in the vendor's terms.
    summary: str
    #: Vendor classification codes that identify this failure outright.
    vendor_codes: tuple[str, ...] = ()
    #: Lowercased substrings of the vendor's message that identify it when
    #: the code does not. Matched case-insensitively.
    message_patterns: tuple[str, ...] = ()


#: What a failure nobody has catalogued resolves to. Retryable on purpose:
#: the observed unclassified failure was a transient one, and refusing to
#: retry an unrecognized error would have left the whole fleet stopped that
#: afternoon. The raw vendor message travels with it so the next reader can
#: turn it into a signature above.
UNCLASSIFIED_VENDOR_ERROR = VendorErrorSignature(
    signature_id="unclassified_vendor_error",
    retryable=True,
    summary="vendor ended the turn on an error no signature recognizes",
)


#: Ordered most specific first: the first entry that matches wins, so a
#: quota wall is never read as a generic capacity failure.
VENDOR_ERROR_SIGNATURES: tuple[VendorErrorSignature, ...] = (
    VendorErrorSignature(
        signature_id="quota_exhausted",
        retryable=False,
        summary="plan quota is spent until the provider's window resets",
        vendor_codes=("usage_limit_reached", "usage_not_included", "rate_limited"),
        message_patterns=(
            "usage limit",
            "rate limit",
            "quota",
            "429",
        ),
    ),
    VendorErrorSignature(
        signature_id="server_overloaded",
        retryable=True,
        summary="provider is at capacity and refused to start the turn",
        vendor_codes=("server_overloaded",),
        message_patterns=("at capacity", "overloaded", "503", "502"),
    ),
    VendorErrorSignature(
        signature_id="client_refused",
        retryable=True,
        summary="provider no longer serves this client build",
        message_patterns=(
            "404 not found",
            "403 forbidden",
            "unsupported client",
            "client version",
        ),
    ),
    VendorErrorSignature(
        signature_id="auth_rejected",
        retryable=False,
        summary="provider rejected the session's credentials",
        vendor_codes=("unauthorized",),
        message_patterns=("401 unauthorized", "invalid api key", "expired token"),
    ),
)


def classify_vendor_error(
    vendor_code: str | None,
    message: str | None,
) -> VendorErrorSignature:
    """Name the failure a turn ended on, never returning nothing.

    ``vendor_code`` is the provider's own classification when it gave one
    (Codex writes it as ``codex_error_info``) and ``message`` is the text
    it wrote alongside. Either may identify the failure and neither is
    required: the live 404 carried the useless code ``"other"``, so only
    its message placed it.

    An unrecognized failure resolves to :data:`UNCLASSIFIED_VENDOR_ERROR`.
    Returning ``None`` would make every caller decide for itself what an
    unknown vendor failure deserves, which is the branching this list
    exists to remove.
    """
    code = str(vendor_code or "").strip().lower()
    text = str(message or "").strip().lower()
    for signature in VENDOR_ERROR_SIGNATURES:
        if code and code in signature.vendor_codes:
            return signature
        if text and any(pattern in text for pattern in signature.message_patterns):
            return signature
    return UNCLASSIFIED_VENDOR_ERROR


__all__ = [
    "UNCLASSIFIED_VENDOR_ERROR",
    "VENDOR_ERROR_SIGNATURES",
    "VendorErrorSignature",
    "classify_vendor_error",
]
