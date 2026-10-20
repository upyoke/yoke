"""What this setup run already did to the world, so replaying it takes the same path.

Some setup steps act as soon as they are answered: the Project step clones the
repository, machine approval saves a connection, a backup restore replaces the
database, Apply registers the checkout. A screen reached again afterwards — by
the wizard's Back and Forward, or by agent mode replaying its stored answers on
the next call — would otherwise re-inspect disk or server state, find this
run's own effect, and branch as if someone else had left it there.

Each such step records its outcome here when it acts, and the screen that would
re-inspect the world reads the fact first. The wizard keeps the facts for its
one process; agent mode saves them in its private setup store the moment they
are recorded, so a later refusal in the same call cannot lose one. Facts are
plain JSON and never hold a secret.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

CLONED_CHECKOUT = "cloned_checkout"
"""The exact folder the Project step cloned the repository into."""

CONNECTION = "connection"
"""The Yoke connection this run saved: destination row, URL, and how it continues."""

BACKUP_IMPORT = "backup_import"
"""A backup import that ran: destination, restored owner, and whether it is uncertain."""

PATH_CHANGED_FILES = "path_changed_files"
"""Shell files Install changed, so the done screen still names them."""

BOARD_ART_SEED = "board_art_seed"
"""The board-art seed Review showed, so Apply writes the same art."""

GIT_INSTALL_STARTED = "git_install_started"
"""The git installer this run already launched."""

LOCAL_UNIVERSE_CREATED = "local_universe_created"
"""Apply or a restore created this machine's local universe."""

APPLY_NEW_FOLDER = "apply_new_folder"
"""A project folder that did not exist until this run's Apply."""

APPLY_NEW_REGISTRATION = "apply_new_registration"
"""A checkout this run's Apply registered on this machine."""

APPLY_NEW_PROJECT = "apply_new_project"
"""The slug of the Yoke project this run's Apply created."""

FACT_NAMES = frozenset(
    {
        CLONED_CHECKOUT,
        CONNECTION,
        BACKUP_IMPORT,
        PATH_CHANGED_FILES,
        BOARD_ART_SEED,
        GIT_INSTALL_STARTED,
        LOCAL_UNIVERSE_CREATED,
        APPLY_NEW_FOLDER,
        APPLY_NEW_REGISTRATION,
        APPLY_NEW_PROJECT,
    }
)


class RunFacts:
    """Named outcomes of this run's effectful steps, keyed by fact name."""

    def __init__(
        self,
        facts: dict[str, Any] | None = None,
        *,
        on_change: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._facts = {k: v for k, v in (facts or {}).items() if k in FACT_NAMES}
        self._on_change = on_change

    def record(self, name: str, value: Any) -> None:
        if name not in FACT_NAMES:
            raise ValueError(f"{name!r} is not a setup run fact")
        if self._facts.get(name) == value:
            return
        self._facts[name] = value
        self._changed()

    def forget(self, name: str) -> None:
        if self._facts.pop(name, None) is not None:
            self._changed()

    def get(self, name: str) -> Any:
        return self._facts.get(name)

    def names_folder(self, name: str, folder: str | Path | None) -> bool:
        """True when fact ``name`` records exactly ``folder``."""
        recorded = self._facts.get(name)
        return bool(recorded and folder) and recorded == checkout_key(folder)

    def cloned_here(self, folder: str | Path) -> bool:
        """True when this run itself cloned the repository into ``folder``."""
        return self.names_folder(CLONED_CHECKOUT, folder)

    def as_record(self) -> dict[str, Any]:
        return dict(self._facts)

    def _changed(self) -> None:
        if self._on_change is not None:
            self._on_change(dict(self._facts))


def checkout_key(folder: str | Path) -> str:
    """The comparable form of a checkout folder: expanded and absolute."""
    return str(Path(folder).expanduser().resolve())


__all__ = [
    "APPLY_NEW_FOLDER",
    "APPLY_NEW_PROJECT",
    "APPLY_NEW_REGISTRATION",
    "BACKUP_IMPORT",
    "BOARD_ART_SEED",
    "CLONED_CHECKOUT",
    "CONNECTION",
    "FACT_NAMES",
    "GIT_INSTALL_STARTED",
    "LOCAL_UNIVERSE_CREATED",
    "PATH_CHANGED_FILES",
    "RunFacts",
    "checkout_key",
]
