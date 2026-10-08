"""Independent symbolic QA ledger: obligations, attempts, judgments and proof.

No production selector, scope, settlement or currency helper calculates this
oracle's expected answer. Tokens represent behavior and subjects deliberately.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Obligation:
    id: int
    scope: tuple[str, ...]
    behavior: str = "original"
    display: str = "case"
    successor: int | None = None
    discharged: bool = False


@dataclass(frozen=True)
class Attempt:
    id: int
    requirement: int
    start: datetime
    verdict: str | None
    completed: bool = True
    review_of: int | None = None
    behavior: str = "original"
    subject: tuple[str, ...] = ()
    proof: bool = True


def current_attempt(attempts: list[Attempt], requirement: int) -> Attempt | None:
    actual = [
        a
        for a in attempts
        if a.requirement == requirement and a.review_of in (None, a.id)
    ]
    return max(actual, key=lambda a: (a.start, a.id), default=None)


def effective(obligations: list[Obligation]) -> list[Obligation]:
    rows = {row.id: row for row in obligations}
    final = {}
    for row in obligations:
        seen = set()
        while row.successor is not None:
            if row.id in seen:
                raise ValueError("cycle")
            seen.add(row.id)
            target = rows.get(row.successor)
            if target is None or row.scope != target.scope:
                raise ValueError("invalid successor scope")
            row = target
        final[row.id] = row
    return list(final.values())


def authorized(obligations: list[Obligation], attempts: list[Attempt]) -> bool:
    for row in effective(obligations):
        if row.discharged:
            continue
        attempt = current_attempt(attempts, row.id)
        if attempt is None or not (
            attempt.completed
            and attempt.verdict == "pass"
            and attempt.proof
            and attempt.behavior == row.behavior
            and attempt.subject == row.scope
        ):
            return False
    return True
