"""Retired shared-operation lease vocabulary after the claim unification.

Migration territory, physical test machines, and private-route
qualification grants are ``work_claims`` rows with their own target kinds
now. The table, its modules, its function-id family, and the retired
command are all gone. "Lease" as a general word is not retired — session
relays and merge locks still take leases — so each pattern names the
retired surface rather than the noun.

Every literal is assembled from fragments so this module does not report
itself, matching the other retired-term modules.
"""

_LEASE = "lease"
_LEASE_TABLE = r"\bcoordination_" + _LEASE + r"s\b"
_LEASE_MODULE = (
    r"\bcoordination_" + _LEASE + r"_(record|contention|reclaim|columns|recovery)\b"
)
_LEASE_CLI = r"\bcoordination-" + _LEASE + r"(-(acquire|heartbeat|list|release))?\b"
_LEASE_FUNCTION = r"\bclaims\.coordination_" + _LEASE + r"\."

COORDINATION_LEASE_RETIREMENT_PATTERNS = (
    _LEASE_TABLE,
    _LEASE_MODULE,
    _LEASE_CLI,
    _LEASE_FUNCTION,
)

COORDINATION_LEASE_RETIREMENT_LABELS = {
    _LEASE_TABLE: (
        "retired shared-operation lock table (holds are work_claims rows: "
        "migration_serialization, qa_admission, route_qualification)"
    ),
    _LEASE_MODULE: (
        "retired shared-operation lock module (use coordination_claims, "
        "coordination_claim_record, coordination_claim_contention, "
        "coordination_claim_keys, coordination_claim_recovery)"
    ),
    _LEASE_CLI: (
        "retired shared-operation lock CLI (use `yoke coordination-claim "
        "list` / `release`)"
    ),
    _LEASE_FUNCTION: (
        "retired shared-operation lock function family "
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
