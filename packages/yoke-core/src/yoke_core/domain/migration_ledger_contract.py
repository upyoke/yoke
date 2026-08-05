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
an entry is pending exactly when its own identity is absent. That is what
this contract requires, and it is why a threshold is refused outright
rather than warned about — a warning would leave the unsound reader in
place while implying it had been reviewed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Set

#: How a ledger decides what has been applied.
MEMBERSHIP = "membership"
#: Rejected: a single high-water mark cannot express the three losses above.
THRESHOLD = "threshold"

REQUIRED_KEYS = ("table", "entry_column", "semantics")


class LedgerContractError(ValueError):
    """A declared ledger cannot answer membership."""


@dataclass(frozen=True)
class LedgerContract:
    """Where applied-ness is recorded and how it is read."""

    table: str
    entry_column: str
    semantics: str = MEMBERSHIP
    serving_floor_column: str = ""

    @property
    def records_serving_floor(self) -> bool:
        """Whether a destructive entry's floor travels with its row.

        Optional because not every project runs builds old enough to be
        stranded, and requiring it would refuse ledgers that are otherwise
        sound. Where it is present, a rolled-back build can answer "can I
        serve this database?" from the row rather than from a history it
        does not ship.
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
    return LedgerContract(
        table=str(declaration["table"]),
        entry_column=str(declaration["entry_column"]),
        semantics=semantics,
        serving_floor_column=str(declaration.get("serving_floor_column") or ""),
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


def unanswerable_reason(
    history: Sequence[str], applied: Iterable[str]
) -> str:
    """Why a ledger cannot answer membership for this history, or ``""``.

    An applied row naming an entry the history does not contain means the
    two are not describing the same history — the likeliest causes are a
    renamed entry or a ledger shared between projects, and both make every
    pending answer meaningless rather than merely stale.
    """
    known = set(history)
    unknown = sorted({str(name) for name in applied} - known)
    if not unknown:
        return ""
    shown = ", ".join(unknown[:5])
    more = f" and {len(unknown) - 5} more" if len(unknown) > 5 else ""
    return (
        f"the ledger records {len(unknown)} entry name(s) absent from the "
        f"shipped history ({shown}{more}); the ledger and the history are "
        "not describing the same migration set"
    )


def runner_config_ledger(declaration: Any, error: Any) -> dict:
    """Normalize a runner-config ledger, raising the caller's error type.

    The error class is injected so the refusal keeps the capability
    validator's own exception type without this module importing it —
    a contract does not depend on the validator that enforces it.

    Callers validate a ledger when the model declares one rather than
    requiring every model to. Models predating this contract are already
    deployed, and refusing them would add a check by taking working
    projects down; new and amended models are refused on the spot.
    """
    try:
        contract = parse(declaration)
    except LedgerContractError as exc:
        raise error(f"runner.config.ledger is invalid: {exc}") from exc
    return {
        "table": contract.table,
        "entry_column": contract.entry_column,
        "semantics": contract.semantics,
        "serving_floor_column": contract.serving_floor_column,
    }


__all__ = [
    "MEMBERSHIP",
    "REQUIRED_KEYS",
    "THRESHOLD",
    "LedgerContract",
    "LedgerContractError",
    "parse",
    "pending_entries",
    "unanswerable_reason",
]
