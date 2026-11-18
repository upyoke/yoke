"""Commit wizard body transitions while their Textual app is running."""

from yoke_cli.config.onboard_wizard_body_scroll import BODY_ID
from yoke_cli.config.onboard_wizard_widgets import Stepper


class BodySwap:
    """Discard queued redraws once the wizard starts shutting down."""

    async def _apply_pending_swap(self) -> None:
        """Drain one body swap, then deliver text captured while it awaited DOM work.

        The pending flag keeps the handler drain and next-tick fallback from
        applying the same transition twice. Raw keys stay buffered until the
        incoming view has registered its input and completed mounting.
        """
        if not self.is_running or not self._swap_pending:
            return
        self._swap_pending = False
        self._body_swap_active = True
        try:
            await self._swap_body()
        finally:
            self._body_swap_active = False
        self._flush_transition_text()

    async def _swap_body(self) -> None:
        if not self.is_running:
            return
        view = self._history[-1]
        body = self.query_one(f"#{BODY_ID}")
        # The batch hides the emptied body; the erased full frame requested after
        # it repaints every cell. The new view starts at the top, not mid-way.
        with self.batch_update():
            await body.remove_children()
            # Shutdown can remove the shell while this awaited unmount settles.
            if not self.is_running:
                return
            body.scroll_home(animate=False)
            # Build before labeling the rail: a view builder may adjust
            # ``_account_step_label`` (the destination picker resets it on every
            # visit, including Esc-back re-renders of the stored view).
            widgets = list(view.builder())
            stepper = self.query_one(Stepper)
            stepper.active = view.step
            stepper.account_label = self._account_step_label
            if self._plain_glyphs:
                self._plainify_widgets(widgets)
            await body.mount(*widgets)
            if not self.is_running:
                return
            # A FocusInput claims focus inside its own on_mount (so the first
            # key after the swap always lands); this re-asserts focus for the
            # SelectionList case and is idempotent for the input case.
            self._focus_first(widgets)
            # The copy and open keys act on whatever the incoming view shows,
            # so they are rebound with it rather than left pointing at the
            # screen the operator just left.
            self._set_copy_targets(view.copy_targets)
        self._request_full_frame()
