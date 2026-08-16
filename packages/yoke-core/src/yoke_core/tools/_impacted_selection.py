"""Selection value and sizing policy for impacted pytest runs."""

from __future__ import annotations

from dataclasses import dataclass

from yoke_core.tools._source_pythonpath import repo_root
from yoke_core.tools.impacted_project_test_roots import resolve_test_roots


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
        return resolve_test_roots(str(repo_root()))

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


__all__ = [
    "MAX_BOUNDED_FILE_FRACTION",
    "MIN_EFFECTIVELY_FULL_FILE_UNIVERSE",
    "Selection",
    "is_effectively_full",
]
