"""Bounded type-to-filter picker for long onboarding lists."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static

from yoke_cli.config.onboard_wizard_widgets import (
    SelectionList,
    SelectionRow,
    _OptionRow,
    _SelectionDescription,
)


class SearchableSelectionList(SelectionList):
    """Show the sorted top of a list immediately and filter as the user types."""

    BINDINGS = [
        *SelectionList.BINDINGS,
        ("backspace", "erase_filter", "erase"),
        ("ctrl+u", "clear_filter", "clear"),
    ]

    def __init__(
        self,
        rows: list[SelectionRow],
        *,
        initial: int = 0,
        viewport_rows: int = 8,
    ) -> None:
        ordered = sorted(rows, key=lambda row: (row.label.casefold(), row.value))
        super().__init__(ordered, initial=initial)
        self._all_rows = ordered
        self._filtered_rows = list(ordered)
        self._query = ""
        self._window_start = 0
        self._viewport_rows = max(1, viewport_rows)

    @property
    def rows(self) -> list[SelectionRow]:
        return self._filtered_rows

    @property
    def selected_value(self) -> str:
        return self._filtered_rows[self.cursor].value

    def compose(self) -> ComposeResult:
        yield Static(id="onboard-search-status", classes="onboard-search-status")
        for _index in range(self._viewport_rows):
            yield _OptionRow(SelectionRow("", "", ""))
        yield _SelectionDescription(classes="onboard-selection-detail")

    def on_mount(self) -> None:
        # The parent's mount fires before its composed status/row children are
        # queryable. Populate the fixed viewport on the next refresh so the
        # complete sorted list is visible before the user types anything.
        self.call_after_refresh(self._sync_selection)

    def on_key(self, event) -> None:
        text = str(getattr(event, "character", "") or "")
        if not text or not text.isprintable() or text.isspace():
            return
        self._query += text
        self._apply_filter()
        event.stop()

    def action_erase_filter(self) -> None:
        if self._query:
            self._query = self._query[:-1]
            self._apply_filter()

    def action_clear_filter(self) -> None:
        if self._query:
            self._query = ""
            self._apply_filter()

    def action_cursor_up(self) -> None:
        if self._filtered_rows:
            self.cursor = max(0, self.cursor - 1)

    def action_cursor_down(self) -> None:
        if self._filtered_rows:
            self.cursor = min(len(self._filtered_rows) - 1, self.cursor + 1)

    def action_choose(self) -> None:
        if self._filtered_rows:
            self.post_message(self.Selected(self.selected_value))

    def _apply_filter(self) -> None:
        needle = self._query.casefold()
        self._filtered_rows = [
            row for row in self._all_rows
            if needle in f"{row.label} {row.hint}".casefold()
        ]
        self.cursor = self._window_start = 0
        self._sync_selection()

    def _sync_selection(self) -> None:
        if not self.is_mounted:
            return
        rows = self._filtered_rows
        if rows:
            self.cursor = min(self.cursor, len(rows) - 1)
            if self.cursor < self._window_start:
                self._window_start = self.cursor
            if self.cursor >= self._window_start + self._viewport_rows:
                self._window_start = self.cursor - self._viewport_rows + 1
        else:
            self.cursor = self._window_start = 0
        query = self._query or "all"
        self.query_one("#onboard-search-status", Static).update(
            f"Filter: {query}  ·  {len(rows)} results"
        )
        visible = rows[self._window_start:self._window_start + self._viewport_rows]
        for index, option in enumerate(self.query(_OptionRow)):
            option.display = index < len(visible)
            if not option.display:
                continue
            option.set_row(visible[index])
            option.set_class(self._window_start + index == self.cursor, "-selected")
        detail = self.query_one(_SelectionDescription)
        detail.update(
            rows[self.cursor].hint
            if rows else "No matches. Clear the filter to restore the list."
        )
        detail.display = True


__all__ = ["SearchableSelectionList"]
