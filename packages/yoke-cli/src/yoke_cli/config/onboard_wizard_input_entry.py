"""How a typed answer reaches the right box and gets committed.

Two shapes of question share these rules. Most steps ask one thing and take one
answer, which a single box covers. A few answers are indivisible — a
credential's key id and its secret are minted together and are useless apart —
and splitting those across screens makes the operator hold half an answer while
the wizard asks for the rest; those steps mount a labelled box per field and
commit the set as one.

The rules are deliberately small and explicit, because a screen with several
focusable controls has to say where typing goes: the first box owns the caret,
Enter finishes a box and moves to the next, Enter on the last box (or the row
that submits the screen) commits every value together, and a rejected value
stops the commit on the box it came from rather than anywhere else.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

from textual.widgets import Input, Static

from yoke_cli.config.onboard_wizard_state import _FormField, _PendingForm
from yoke_cli.config.onboard_wizard_widgets import FocusInput


def form_field_widgets(fields: Sequence[_FormField]) -> list[Static]:
    """Label, box, and inline error slot for each field, in order.

    The error slots stay collapsed until something is written into one, so a
    screen that fills its frame keeps its row budget while it is being filled in
    correctly and spends a row only when it has a correction to show.
    """
    widgets: list[Static] = []
    for index, field in enumerate(fields):
        widgets.append(Static(f"  {field.label}", classes="onboard-plan-line"))
        widgets.append(FocusInput(
            placeholder=field.placeholder,
            password=field.password,
            id=field.input_id,
            classes="onboard-input onboard-form-input",
            claim_focus=index == 0,
        ))
        widgets.append(Static("", id=field.error_id, classes="onboard-field-error"))
    return widgets


class InputEntry:
    """Entry rules for every view that takes a typed answer."""

    # ── keystroke rescue ────────────────────────────────────

    def on_key(self, event: Any) -> None:
        text = str(getattr(event, "character", "") or "")
        if not text or not text.isprintable():  # Enter is "\r"; controls stay with widgets
            return
        target = self._active_input()
        if target is not None and not target.has_focus:
            # Key arrived before the freshly mounted Input settled focus: place
            # it manually so the leading character is never dropped. Once the
            # Input owns focus, Textual delivers keys to it directly and this
            # branch is a no-op (guarded by `not target.has_focus`), so the
            # event is never inserted twice.
            self.set_focus(target)
            self._insert_input_text(target, text)
            event.stop()

    def _active_input(self) -> Input | None:
        """The box a stray keystroke belongs to: the focused one, else the first.

        On a screen with several boxes the rescue above must not always feed the
        first field — once focus has moved on, the character belongs where the
        caret is. Before any box has settled focus, the first one is the target.
        """
        if self._pending_input is None and self._pending_form is None:
            return None
        body = self.query_one("#onboard-body")
        boxes = [
            widget for widget in body.children
            if isinstance(widget, Input) and not widget.disabled
        ]
        for widget in boxes:
            if widget.has_focus:
                return widget
        return boxes[0] if boxes else None

    def _insert_input_text(self, widget: Input, text: str) -> None:
        value = widget.value or ""
        cursor = int(getattr(widget, "cursor_position", len(value)) or 0)
        widget.value = value[:cursor] + text + value[cursor:]
        widget.cursor_position = cursor + len(text)

    # ── submission ──────────────────────────────────────────

    async def on_input_submitted(self, message: Input.Submitted) -> None:
        if self._pending_form is not None:
            self._advance_form(message.input)
            await self._apply_pending_swap()
            return
        if self._pending_input is None:
            return
        value = message.value.strip()
        if not value and self._pending_input.allow_placeholder:
            value = self._pending_input.placeholder.strip()
        # Fail fast: reject invalid input inline and stay on this step so the user
        # re-enters, instead of advancing and surfacing the failure at Apply.
        if self._pending_input.validate is not None:
            error = self._pending_input.validate(value)
            if error:
                self._show_input_error(error)
                return
        if not value:
            self._show_input_error("A value is required.")
            return
        pending = self._pending_input
        self._pending_input = None
        pending.on_done(value)
        await self._apply_pending_swap()

    def _show_input_error(self, text: str) -> None:
        for widget in self.query(".onboard-input-error").results(Static):
            widget.update(text)

    # ── several boxes at once ───────────────────────────────

    def _begin_form(
        self,
        fields: tuple[_FormField, ...],
        *,
        on_done: Callable[[dict[str, str]], None],
    ) -> None:
        """Register the fields the body about to mount collects.

        Called from a view's builder, like the single-input path, so the pending
        state and the widgets it describes are created in the same turn.
        """
        self._pending_form = _PendingForm(fields=fields, on_done=on_done)

    def _form_boxes(self) -> list[Input]:
        """The mounted box for each pending field, in field order."""
        if self._pending_form is None:
            return []
        body = self.query_one("#onboard-body")
        mounted = {
            widget.id: widget
            for widget in body.children
            if isinstance(widget, Input)
        }
        boxes = [mounted.get(field.input_id) for field in self._pending_form.fields]
        return [box for box in boxes if box is not None]

    def _advance_form(self, box: Input) -> None:
        """Enter on a field: check it, then move on — or commit from the last.

        Enter reads as "done with this one" everywhere else in the wizard, so
        here it advances rather than submitting a half-filled answer; only the
        last box commits the set.
        """
        form = self._pending_form
        if form is None:
            return
        boxes = self._form_boxes()
        if box not in boxes:
            return
        index = boxes.index(box)
        if not self._check_form_field(form.fields[index], box):
            return
        if index + 1 < len(boxes):
            self.set_focus(boxes[index + 1])
            return
        self._submit_pending_form()

    def _submit_pending_form(self) -> bool:
        """Check every field, then hand the whole value set to the view.

        The row that submits the screen and Enter on its last box are the same
        commit, so both land here. A rejected value stops the commit on the box
        it came from, puts the caret there, and hands nothing on.
        """
        form = self._pending_form
        if form is None:
            return False
        boxes = self._form_boxes()
        if len(boxes) < len(form.fields):
            return False
        for field in form.fields:
            self._show_field_error(field, "")
        for field, box in zip(form.fields, boxes):
            if not self._check_form_field(field, box):
                self.set_focus(box)
                return False
        values = {
            field.key: (box.value or "").strip()
            for field, box in zip(form.fields, boxes)
        }
        self._pending_form = None
        form.on_done(values)
        return True

    def _check_form_field(self, field: _FormField, box: Input) -> bool:
        value = (box.value or "").strip()
        error = field.validate(value) if field.validate is not None else None
        if error is None and not value:
            error = "A value is required."
        self._show_field_error(field, error or "")
        return error is None

    def _show_field_error(self, field: _FormField, text: str) -> None:
        """Write an inline error into one field's slot, leaving its neighbours be."""
        slot = self.query_one(f"#{field.error_id}", Static)
        slot.update(text)
        slot.set_class(bool(text), "-shown")


__all__ = ["InputEntry", "form_field_widgets"]
