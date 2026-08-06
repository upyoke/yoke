"""What a project's migration ledger must be able to answer.

A project declaring a ``migration_model`` says where its migrations live
and what they connect to. It has said nothing about how applied-ness is
decided, and that omission is load-bearing: a project can satisfy every
authoring gate, every rehearsal, and every compatibility check, and then
apply its migrations with semantics that silently skip entries.

The unsound shape is a high-water mark — record the highest version that
ran, treat everything above it as pending. It loses three different ways:

- A skipped entry becomes permanently invisible. If ``003`` fails while
  ``004`` succeeds, the mark is 4 and nothing above 4 includes 3 again.
- A rollback reports itself current. The mark still names the newer entry,
  so an older build computes an empty pending set while reading a schema
  it does not know.
- Out-of-order merges drop an entry. Two branches each add a number; if the
  higher lands first, the lower is never pending.

Membership answers all three: the pending set is ``history - applied``, so
an entry is pending exactly when its own identity is absent.

Membership alone is still not rollback-safe. A rolled-back build's history
genuinely lacks a newer destructive entry, so membership reports current
while the build reads a surface that is gone. The serving floor closes that
gap: each applied row records the oldest build that may serve against it,
and a build too old to ship the entry module answers the serving question
from the row — the only surface the two builds share.

Rollback-safety contract for a declaring project
================================================

A project's boot must answer two questions before it serves, and refuse
when either answer is unsafe:

1. **Pending membership** — is every shipped history entry recorded in the
   ledger? Refuse to serve when the pending set is non-empty (the schema
   this code expects has not been applied).
2. **Serving floor** — does any applied row record a floor newer than this
   build? Refuse to serve when stranded (this build reads surfaces a newer
   entry removed).

What must be recorded per applied entry so a rolled-back build can answer
from the ledger row alone:

- the entry's identity (``entry_column``), so membership is decidable;
- the raw-byte content digest (``digest_column``), so a permanent name cannot
  silently begin naming different migration code;
- the serving floor (``serving_floor_column``), copied from a destructive
  entry's declared minimum at apply time — empty/NULL only when that entry
  did not remove a surface.

The normalized declaration surface expresses every element this contract
requires: ``table``, ``entry_column``, ``digest_column``,
``semantics=membership``, and ``serving_floor_column``. Declarations stored
before content identity existed normalize an omitted digest column to the
project-neutral standard ``content_sha256``; new declarations emit it
explicitly. Leaving the floor optional and unconsumed remains refused.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Set

#: How a ledger decides what has been applied.
MEMBERSHIP = "membership"
#: Rejected: a single high-water mark cannot express the three losses above.
THRESHOLD = "threshold"
DEFAULT_DIGEST_COLUMN = "content_sha256"
DEFAULT_APPLIED_AT_COLUMN = "applied_at"
DEFAULT_APPLIED_BY_COLUMN = "applied_by"

REQUIRED_KEYS = (
    "table",
    "entry_column",
    "semantics",
    "serving_floor_column",
)
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class LedgerContractError(ValueError):
    """A declared ledger cannot answer the rollback-safety contract."""


@dataclass(frozen=True)
class LedgerContract:
    """Where membership, content identity, and serving floors are recorded."""

    table: str
    entry_column: str
    digest_column: str
    serving_floor_column: str
    semantics: str = MEMBERSHIP
    applied_at_column: str = DEFAULT_APPLIED_AT_COLUMN
    applied_by_column: str = DEFAULT_APPLIED_BY_COLUMN

    @property
    def records_serving_floor(self) -> bool:
        """Whether a destructive entry's floor travels with its row.

        Always true for a successfully parsed declaration: the serving
        floor is required so a rolled-back build can answer "can I serve
        this database?" from the row rather than from a history it does
        not ship.
        """
        return bool(self.serving_floor_column)


def parse(declaration: Optional[Mapping[str, Any]]) -> LedgerContract:
    """Read a ledger declaration, refusing anything that cannot answer.

    Refuses rather than defaults. A missing declaration is the state every
    project had before this contract existed, so silently supplying one
    would reintroduce exactly the unchecked assumption at issue.
    """
    if not declaration:
        raise LedgerContractError(
            "migration_model declares no ledger; add a ledger with "
            f"{', '.join(REQUIRED_KEYS)} so applied-ness can be decided"
        )
    missing = [key for key in REQUIRED_KEYS if not declaration.get(key)]
    if missing:
        raise LedgerContractError(
            f"migration_model ledger is missing {', '.join(missing)}"
        )
    semantics = str(declaration["semantics"])
    if semantics == THRESHOLD:
        raise LedgerContractError(
            "migration_model ledger declares threshold semantics, which "
            "cannot express a skipped entry, a rollback, or an "
            f"out-of-order merge; use {MEMBERSHIP!r}"
        )
    if semantics != MEMBERSHIP:
        raise LedgerContractError(
            f"migration_model ledger declares unknown semantics "
            f"{semantics!r}; the only accepted value is {MEMBERSHIP!r}"
        )
    identifiers = {
        "table": str(declaration["table"]),
        "entry_column": str(declaration["entry_column"]),
        "digest_column": str(
            declaration.get("digest_column") or DEFAULT_DIGEST_COLUMN
        ),
        "serving_floor_column": str(declaration["serving_floor_column"]),
        "applied_at_column": str(
            declaration.get("applied_at_column") or DEFAULT_APPLIED_AT_COLUMN
        ),
        "applied_by_column": str(
            declaration.get("applied_by_column") or DEFAULT_APPLIED_BY_COLUMN
        ),
    }
    invalid = [key for key, value in identifiers.items() if not _IDENTIFIER.match(value)]
    if invalid:
        raise LedgerContractError(
            "migration_model ledger has unsafe SQL identifier(s): "
            + ", ".join(invalid)
        )
    return LedgerContract(
        table=identifiers["table"],
        entry_column=identifiers["entry_column"],
        digest_column=identifiers["digest_column"],
        semantics=semantics,
        serving_floor_column=identifiers["serving_floor_column"],
        applied_at_column=identifiers["applied_at_column"],
        applied_by_column=identifiers["applied_by_column"],
    )


def pending_entries(
    history: Sequence[str], applied: Iterable[str]
) -> List[str]:
    """The entries this database still owes, in history order.

    Membership, not comparison: order in the history decides *when* an
    entry runs, never *whether* it is owed.
    """
    recorded: Set[str] = {str(name) for name in applied}
    return [name for name in history if name not in recorded]


def applied_entries_outside_history(
    history: Sequence[str], applied: Iterable[str]
) -> List[str]:
    """Applied entries this packaged history does not ship.

    This is the normal shape of a rollback: an older artifact reads ledger
    rows written by a newer artifact. It does not invalidate membership.
    Rollback compatibility is decided from each row's recorded serving floor,
    because the older artifact cannot consult migration modules it does not
    ship.
    """
    known = set(history)
    return sorted({str(name) for name in applied} - known)


def runner_config_ledger(declaration: Any, error: Any) -> dict:
    """Normalize a runner-config ledger, raising the caller's error type.

    The error class is injected so the refusal keeps the capability
    validator's own exception type without this module importing it —
    a contract does not depend on the validator that enforces it.

    Every governed model must declare a ledger. A missing declaration cannot
    answer either safety question, so the capability validator refuses it
    instead of grandfathering an unchecked model.
    """
    try:
        contract = parse(declaration)
    except LedgerContractError as exc:
        raise error(f"runner.config.ledger is invalid: {exc}") from exc
    return {
        "table": contract.table,
        "entry_column": contract.entry_column,
        "digest_column": contract.digest_column,
        "semantics": contract.semantics,
        "serving_floor_column": contract.serving_floor_column,
        "applied_at_column": contract.applied_at_column,
        "applied_by_column": contract.applied_by_column,
    }


__all__ = [
    "MEMBERSHIP",
    "DEFAULT_APPLIED_AT_COLUMN",
    "DEFAULT_APPLIED_BY_COLUMN",
    "DEFAULT_DIGEST_COLUMN",
    "REQUIRED_KEYS",
    "THRESHOLD",
    "LedgerContract",
    "LedgerContractError",
    "applied_entries_outside_history",
    "parse",
    "pending_entries",
]
