"""What this setup run already did to the world, so replaying it takes the same path.

Some setup steps act as soon as they are answered: the Project step clones the
repository into the named folder. A screen reached again afterwards — by the
wizard's Back and Forward, or by agent mode replaying its stored answers on the
next call — would otherwise re-inspect disk or server state and find this
run's own effect, then ask about it as if someone else had left it there.

Each such step records its outcome here when it acts, and the screen that would
re-inspect the world reads the fact first. The wizard keeps the facts for its
one process; agent mode saves them in its private setup store the moment they
are recorded, so a later refusal in the same call cannot lose one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

CLONED_CHECKOUT = "cloned_checkout"
"""The exact folder this run cloned the project repository into."""

FACT_NAMES = frozenset({CLONED_CHECKOUT})


class RunFacts:
    """Named outcomes of this run's effectful steps, keyed by fact name."""

    def __init__(
        self,
        facts: dict[str, str] | None = None,
        *,
        on_change: Callable[[dict[str, str]], None] | None = None,
    ) -> None:
        self._facts = {k: v for k, v in (facts or {}).items() if k in FACT_NAMES}
        self._on_change = on_change

    def record(self, name: str, value: str) -> None:
        if name not in FACT_NAMES:
            raise ValueError(f"{name!r} is not a setup run fact")
        if self._facts.get(name) == value:
            return
        self._facts[name] = value
        if self._on_change is not None:
            self._on_change(dict(self._facts))

    def get(self, name: str) -> str | None:
        return self._facts.get(name)

    def cloned_here(self, folder: str | Path) -> bool:
        """True when this run itself cloned the repository into ``folder``."""
        cloned = self._facts.get(CLONED_CHECKOUT)
        return cloned is not None and cloned == checkout_key(folder)

    def as_record(self) -> dict[str, str]:
        return dict(self._facts)


def checkout_key(folder: str | Path) -> str:
    """The comparable form of a checkout folder: expanded and absolute."""
    return str(Path(folder).expanduser().resolve())


__all__ = ["CLONED_CHECKOUT", "FACT_NAMES", "RunFacts", "checkout_key"]
