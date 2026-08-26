"""Retired shared-operation lease vocabulary after the claim unification.

Migration territory, physical test machines, and private-route
qualification grants are ``work_claims`` rows with their own target kinds
now. The table, its modules, its function-id family, and the
``coordination-lease`` command are all gone. "Lease" as a general word is
not retired — session relays and merge locks still take leases — so each
pattern names the retired surface rather than the noun.
"""

_LEASE_TABLE = r"\b" + "coordination_leases" + r"\b"
_LEASE_MODULE = (
    r"\b" + "coordination_lease" + r"_(record|contention|reclaim|columns|recovery)\b"
)
_LEASE_CLI = r"\b" + "coordination-lease" + r"(-(acquire|heartbeat|list|release))?\b"
_LEASE_FUNCTION = r"\b" + "claims" + r"\." + "coordination_lease" + r"\."

COORDINATION_LEASE_RETIREMENT_PATTERNS = (
    _LEASE_TABLE,
    _LEASE_MODULE,
    _LEASE_CLI,
    _LEASE_FUNCTION,
)

COORDINATION_LEASE_RETIREMENT_LABELS = {
    _LEASE_TABLE: (
        "retired shared-operation lease table (holds are work_claims rows: "
        "migration_serialization, qa_admission, route_qualification)"
    ),
    _LEASE_MODULE: (
        "retired coordination-lease module (use coordination_claims, "
        "coordination_claim_record, coordination_claim_contention, "
        "coordination_claim_keys, coordination_claim_recovery)"
    ),
    _LEASE_CLI: (
        "retired coordination-lease CLI (use `yoke coordination-claim list` "
        "/ `release`)"
    ),
    _LEASE_FUNCTION: (
        "retired claims.coordination_lease.* function family "
        "(use claims.coordination_claim.*)"
    ),
}

#: The history entry that retires the table names it as its subject, as
#: does the released entry that once backfilled its columns, and both
#: ledger rows must keep resolving by name forever.
COORDINATION_LEASE_RETIREMENT_ALLOWLIST = {
    pattern: (
        "packages/yoke-core/src/yoke_core/domain/migrations/",
        "docs/archive/",
    )
    for pattern in COORDINATION_LEASE_RETIREMENT_PATTERNS
}

__all__ = [
    "COORDINATION_LEASE_RETIREMENT_ALLOWLIST",
    "COORDINATION_LEASE_RETIREMENT_LABELS",
    "COORDINATION_LEASE_RETIREMENT_PATTERNS",
]
