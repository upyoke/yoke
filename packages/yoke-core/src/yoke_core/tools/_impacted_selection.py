"""Selection value and sizing policy for impacted pytest runs."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from yoke_core.tools.impacted_project_test_roots import current_test_roots


MAX_BOUNDED_FILE_FRACTION = 0.8
MIN_EFFECTIVELY_FULL_FILE_UNIVERSE = 100


@dataclass(frozen=True)
class Selection:
    """Test files to run, their universe, and the reason for the choice."""

    full_sweep: bool
    reason: str
    files: tuple[str, ...] = ()
    total_files: int | None = None
    selected_items: int | None = None
    total_items: int | None = None
    fallback_rule: str = ""
    trigger_paths: tuple[str, ...] = ()
    widening_triggers: tuple[str, ...] = ()
    bounded_deferral: bool = False

    def pytest_paths(self) -> tuple[str, ...]:
        if not self.full_sweep:
            return self.files
        return current_test_roots()

    def count_summary(self) -> str:
        selected_files = self.total_files if self.full_sweep else len(self.files)
        selected = "unknown" if selected_files is None else str(selected_files)
        total = "unknown" if self.total_files is None else str(self.total_files)
        items = "unknown" if self.selected_items is None else str(self.selected_items)
        total_items = "unknown" if self.total_items is None else str(self.total_items)
        return f"files={selected} of {total} items={items} of {total_items}"

    def telemetry(self) -> str:
        if self.full_sweep:
            scope = "full_sweep"
        elif self.bounded_deferral:
            scope = "bounded_deferral"
        else:
            scope = "impacted"
        fields = [f"scope={scope}", f"rule={self.fallback_rule or 'none'}"]
        fields.append(f"triggers={','.join(self.trigger_paths) or 'none'}")
        if self.widening_triggers:
            fields.append(f"widening={','.join(self.widening_triggers)}")
        fields.append(self.count_summary())
        return "impacted-selection " + " ".join(fields)


def is_effectively_full(selected_files: int, total_files: int) -> bool:
    """Whether a selected file set is too broad for bounded iteration."""
    return bool(
        total_files >= MIN_EFFECTIVELY_FULL_FILE_UNIVERSE
        and selected_files / total_files >= MAX_BOUNDED_FILE_FRACTION
    )


def remainder_paths_for_bounded_reachability(
    remainder: Sequence[str],
    *,
    total_files: int,
    individually_reached: Callable[[str], int],
) -> tuple[str, ...]:
    """Remainder paths whose own reachability is still a bounded subset.

    An unmapped file excludes only itself. Walking every leftover Python
    path as one query can look near-total even when some of those paths
    are small; drop the individually near-total paths before the rest.
    """
    return tuple(
        path
        for path in remainder
        if not is_effectively_full(individually_reached(path), total_files)
    )


__all__ = [
    "MAX_BOUNDED_FILE_FRACTION",
    "MIN_EFFECTIVELY_FULL_FILE_UNIVERSE",
    "Selection",
    "is_effectively_full",
    "remainder_paths_for_bounded_reachability",
]
