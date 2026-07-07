"""Textual ``App`` shell and flow control for the ``yoke onboard`` wizard.

One screen redraws in place: a fixed header, stepper, and footer stay mounted
while the body container is recomposed per view. Free-text entry (token paste,
checkout path, project metadata) swaps the body to a focused input view; every
other decision is an arrow-key :class:`SelectionList`. Esc steps back; Ctrl+C
quits cleanly. No view ever displays a secret — token inputs are password
fields. Per-step body builders live in :mod:`onboard_wizard_steps`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Input, Rule, Static

from yoke_cli.config.onboard_terminal import (
    glyphs,
    plain_glyphs,
    plain_text,
    screen_compat_terminal,
)
from yoke_cli.config import machine_config
from yoke_cli.config import onboard_destinations
from yoke_cli.config.onboard_wizard import (
    WizardDefaults,
    WizardResult,
    default_config_path,
)
from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config.onboard_wizard_checking import CheckingFlow
from yoke_cli.config.onboard_wizard_palette import ACCENT, DIM, TEXT
from yoke_cli.config.onboard_wizard_flow import WizardFlow
from yoke_cli.config.onboard_wizard_flow_apply import ApplyFlow
from yoke_cli.config.onboard_wizard_flow_board_art import BoardArtFlow
from yoke_cli.config.onboard_wizard_flow_clone import CloneFlow
from yoke_cli.config.onboard_wizard_flow_connect import ConnectFlow
from yoke_cli.config.onboard_wizard_flow_destination import DestinationFlow
from yoke_cli.config.onboard_wizard_flow_dev import DevFlow
from yoke_cli.config.onboard_wizard_flow_github import MachineGithubFlow
from yoke_cli.config.onboard_wizard_flow_project_git import ProjectGitFlow
from yoke_cli.config.onboard_wizard_flow_publish import PublishFlow
from yoke_cli.config.onboard_wizard_path import PathFlow
from yoke_cli.config.onboard_wizard_state import _PendingInput, _View
from yoke_cli.config.onboard_wizard_widgets import (
    STEP_CONNECT_LABEL,
    SelectionList,
    Stepper,
)


def _footer_hint(glyph: str, label: str) -> str:
    """One footer hint: a bright key glyph and its dim label."""
    return f"[{TEXT}]{glyph}[/] [{DIM}]{label}[/]"


# Key glyphs render bright, their labels dim, so the keys read at a glance while
# the labels recede.
_MOUSE_REPORTING_OFF = "\x1b[?1000l\x1b[?1002l\x1b[?1003l\x1b[?1006l"


def _header() -> str:
    marks = glyphs()
    return (
        f"[bold {ACCENT}]{marks.header_mark} Yoke[/]  "
        f"[#7d8590]{marks.header_sep} "
        "Set up your machine and onboard your projects[/]"
    )


def _footer() -> str:
    marks = glyphs()
    return "     ".join(
        _footer_hint(glyph, label)
        for glyph, label in (
            (marks.footer_navigate, "navigate"),
            (marks.footer_select, "select"),
            ("esc", "back"),
            ("^c", "quit"),
        )
    )


def _disable_mouse_reporting() -> None:
    sys.stdout.write(_MOUSE_REPORTING_OFF)
    sys.stdout.flush()


class OnboardWizardApp(
    CheckingFlow, PathFlow, DestinationFlow, ConnectFlow, MachineGithubFlow,
    ProjectGitFlow, WizardFlow, ApplyFlow, CloneFlow, DevFlow, PublishFlow,
    BoardArtFlow, App[None],
):
    CSS_PATH = "onboard_wizard.tcss"
    BINDINGS = [
        Binding("escape", "back", "back", show=False),
        Binding("ctrl+[", "back", "back", show=False),
        Binding("ctrl+c", "quit_wizard", "quit", show=False, priority=True),
    ]

    def __init__(
        self,
        *,
        defaults: WizardDefaults,
        apply_report: Callable[..., Any],
    ) -> None:
        super().__init__()
        self._apply_report = apply_report
        self.cancelled = False
        self.exit_code = 0
        self.last_error: str | None = None
        self.failed_step: str | None = None
        self.report_path: str | None = None
        self.resume_command: str | None = None
        self._stored_yoke_token_available = False
        self._stored_yoke_attempted = False
        self._stored_github_attempted = False
        self._stored_machine_github_token_file: str | None = None
        self._stored_machine_github_api_url: str | None = None
        self._stored_project_attempted = False
        self._stored_project_checkouts: list[machine_config.ConfiguredProject] = []
        self._pending_stored_project_checkout: str | None = None
        # Apply runs in a worker thread (ApplyFlow): ``_applying`` guards ctrl-C
        # from a mid-mutation teardown; ``_apply_steps`` is the live step model;
        # ``_review_plan`` is the previewed plan the Applying screen renders from.
        self._applying = False
        self._apply_steps: list[dict[str, Any]] = []
        self._review_plan: dict[str, Any] = {}
        self._review_problems: list[str] = []
        self._review_notes: list[str] = []
        self._resume_run_id: str | None = None
        self._resume_payload: dict[str, Any] | None = None
        # A destination preset (CLI flags, the destination env override, or a
        # resumed run) skips the picker; the Account rail label follows the
        # routed destination on every body swap.
        self._destination_preset = defaults.destination is not None
        self._account_step_label = STEP_CONNECT_LABEL
        self.result = WizardResult(
            config_path=default_config_path(defaults.config_path),
            env_name=(defaults.env_name or onboard_destinations.DEFAULT_SIGN_IN_ENV),
            api_url=(defaults.api_url or ""),
            destination=(
                defaults.destination or onboard_destinations.DEFAULT_DESTINATION
            ),
            token=defaults.token,
            token_file=defaults.token_file,
            mode=(defaults.mode or "quick"),
            apply=defaults.apply,
        )
        self._hydrate_stored_credentials(defaults)
        self._post_install = defaults.post_install
        self._history: list[_View] = []
        self._pending_input: _PendingInput | None = None
        self._checking = False
        # Set by ``_render_current`` and drained by the async message handlers so
        # the body swap runs in the same handler turn as the transition keypress.
        self._swap_pending = False
        # login -> github_publish.RepoOwner for the chosen publish owner picker.
        self._owner_lookup: dict[str, Any] = {}
        self._screen_compat = screen_compat_terminal()
        self._plain_glyphs = plain_glyphs()

    def compose(self) -> ComposeResult:
        yield Static(_header(), id="onboard-header", markup=True)
        yield Stepper(id="onboard-stepper")
        yield self._divider()
        # Non-focusable: a scroll container that can take focus would steal it
        # from the active SelectionList/Input on a body click and leave Enter
        # dead. on_click then refocuses the active control for header/footer/
        # label clicks too.
        if self._plain_glyphs:
            body = Vertical(id="onboard-body")
        else:
            body = VerticalScroll(id="onboard-body", can_focus=False)
        yield body
        yield self._divider()
        yield Static(_footer(), id="onboard-footer", markup=True)

    def _divider(self) -> Rule | Static:
        if self._screen_compat or self._plain_glyphs:
            return Static("", classes="onboard-divider")
        return Rule(classes="onboard-divider")

    def _hydrate_stored_credentials(self, defaults: WizardDefaults) -> None:
        """Preload reusable token-file references from machine config.

        The wizard still verifies every secret before using it. This only saves
        the operator from re-entering file paths already recorded in the machine
        config. Project checkouts are also only preloaded here; the Project step
        verifies the stored project id with the API before reusing one.
        """

        self._hydrate_stored_yoke_connection(defaults)
        self._hydrate_stored_github_connection()
        self._hydrate_stored_project_checkouts()

    def _hydrate_stored_yoke_connection(self, defaults: WizardDefaults) -> None:
        if defaults.token or defaults.token_file:
            return
        try:
            connection = machine_config.active_connection(
                self.result.config_path,
                explicit_env=defaults.env_name,
            )
        except (OSError, RuntimeError, ValueError):
            return
        if str(connection.get("transport") or "") != "https":
            return
        api_url = str(connection.get("api_url") or "").strip()
        if not api_url:
            return
        if defaults.api_url and defaults.api_url.strip() != api_url:
            return
        source = connection.get("credential_source")
        if not isinstance(source, dict) or source.get("kind") != "token_file":
            return
        token_file = str(source.get("path") or "").strip()
        if not token_file:
            return
        token_path = Path(token_file).expanduser()
        if not token_path.is_file():
            return
        self.result.env_name = str(connection.get("env") or self.result.env_name)
        if not self.result.api_url:
            self.result.api_url = api_url
        self.result.token_file = str(token_path)
        self.result.token_source_kind = "token_file"
        self._stored_yoke_token_available = True

    def _hydrate_stored_github_connection(self) -> None:
        try:
            github = machine_config.github_config(self.result.config_path)
        except (OSError, RuntimeError, ValueError):
            return
        source = github.get("credential_source")
        if not isinstance(source, dict) or source.get("kind") != "token_file":
            return
        token_file = str(source.get("path") or "").strip()
        if not token_file:
            return
        token_path = Path(token_file).expanduser()
        if not token_path.is_file():
            return
        self._stored_machine_github_token_file = str(token_path)
        self._stored_machine_github_api_url = str(
            github.get("api_url") or "https://api.github.com"
        ).strip()

    def _hydrate_stored_project_checkouts(self) -> None:
        try:
            self._stored_project_checkouts = machine_config.configured_projects(
                self.result.config_path,
                existing_only=True,
            )
        except (OSError, RuntimeError, ValueError):
            self._stored_project_checkouts = []

    async def on_mount(self) -> None:
        if self._plain_glyphs:
            self.screen.add_class("plain-glyphs")
        if self._screen_compat:
            _disable_mouse_reporting()
        self._start_front()
        await self._apply_pending_swap()

    # ── flow control ────────────────────────────────────────

    def _goto(self, view: _View) -> None:
        self._history.append(view)
        self._render_current()

    def _replace_current(self, view: _View) -> None:
        """Swap the current view in place without growing history (Applying ->
        success/failure), so a later Esc never lands on a non-interactive screen."""
        if self._history:
            self._history[-1] = view
        else:
            self._history.append(view)
        self._render_current()

    def _render_current(self) -> None:
        # Mark a swap as pending and disable the outgoing input *now*, before any
        # await yields control back to the message loop. A still-focused outgoing
        # Input would otherwise swallow a keystroke typed during the transition
        # (the leading "~" of a path is the painful case); disabling it drops its
        # focus immediately so no key lands in a widget that is about to vanish.
        self._pending_input = None
        self._swap_pending = True
        body = self.query_one("#onboard-body")
        for widget in body.children:
            if isinstance(widget, Input):
                widget.disabled = True
        # The async message handlers drain the swap synchronously in the same
        # handler turn the transition keypress drove (so there is never an idle
        # tick where the new input is unmounted yet keys can still be dispatched).
        # This next-tick fallback covers any path that reaches _render_current
        # outside a draining handler — chiefly tests that call a flow method
        # directly — so the swap still settles on the next message-loop tick.
        self.call_later(self._apply_pending_swap)

    async def _apply_pending_swap(self) -> None:
        """Perform the recorded body swap synchronously, if one is pending.

        Each async message handler calls this after the synchronous flow routing
        runs, so the DOM swap + focus complete within the same handler turn that
        the transition keypress drove — no deferred window during which a
        keystroke could be lost. Idempotent: the pending flag guards against the
        handler drain and the next-tick fallback both firing for one transition.
        """
        if not self._swap_pending:
            return
        self._swap_pending = False
        await self._swap_body()

    async def _swap_body(self) -> None:
        view = self._history[-1]
        body = self.query_one("#onboard-body")
        await body.remove_children()
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
        # A FocusInput claims focus inside its own on_mount (so the first key
        # after the swap always lands); this re-asserts focus for the
        # SelectionList case and is idempotent for the input case.
        self._focus_first(widgets)

    def _plainify_widgets(self, widgets: list[Static]) -> None:
        for widget in widgets:
            if isinstance(widget, Static) and not isinstance(widget, Stepper):
                widget.update(plain_text(str(widget.render())))
            if isinstance(widget, Input):
                widget.placeholder = plain_text(str(widget.placeholder or ""))

    def _focus_first(self, widgets: list[Static]) -> Static | None:
        for widget in widgets:
            if isinstance(widget, (SelectionList, Input)):
                self.set_focus(widget)
                return widget
        return None

    def _refocus_body(self) -> None:
        """Move focus to the body's first focusable child (SelectionList/Input).

        The body is a non-focusable VerticalScroll, so a click on empty body
        space would otherwise clear focus off the active list — leaving the
        highlighted row in place while Enter silently no-ops. Re-running the
        same focus rule the body uses on mount keeps Enter live after any click.
        """
        body = self.query_one("#onboard-body", VerticalScroll)
        self._focus_first(list(body.children))

    def on_click(self, event: Any) -> None:
        if self._screen_compat:
            return
        # Any click that lands on the body chrome (the non-focusable scroll
        # container, the header/stepper/footer, or a static label) restores
        # focus to the active control so Enter never goes dead.
        self._refocus_body()

    def on_key(self, event: Any) -> None:
        text = str(getattr(event, "character", "") or "")
        if not text:
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
        if self._pending_input is None:
            return None
        body = self.query_one("#onboard-body", VerticalScroll)
        for widget in body.children:
            if isinstance(widget, Input) and not widget.disabled:
                return widget
        return None

    def _insert_input_text(self, widget: Input, text: str) -> None:
        value = widget.value or ""
        cursor = int(getattr(widget, "cursor_position", len(value)) or 0)
        widget.value = value[:cursor] + text + value[cursor:]
        widget.cursor_position = cursor + len(text)

    async def action_back(self) -> None:
        if self._checking:
            return
        if len(self._history) > 1:
            self._pending_input = None
            self._history.pop()
            self._render_current()
            await self._apply_pending_swap()

    def action_quit_wizard(self) -> None:
        # Apply is an atomic worker-thread transaction that can't be killed mid-
        # flight; quitting here is the mid-mutation cliff (after clone, before
        # push) onboarding must avoid. Suppress quit while applying — the worker
        # finalizes the report and routes to success/failure, where Exit lives.
        if self._applying:
            return
        self.cancelled = True
        self.exit_code = 130
        self.exit()

    # ── message routing ─────────────────────────────────────

    async def on_selection_list_selected(self, message: SelectionList.Selected) -> None:
        handler = self._history[-1].on_select
        if handler is not None:
            handler(message.value)
        await self._apply_pending_swap()

    async def on_input_submitted(self, message: Input.Submitted) -> None:
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

    # ── view helpers ────────────────────────────────────────

    def _selection_view(self, step, title, subtitle, rows, on_select,
                        *, initial: int = 0) -> _View:
        return _View(
            step,
            lambda: steps.selection_body(title, subtitle, rows, initial=initial),
            on_select,
        )

    def _input_view(
        self, step, title, subtitle, *, placeholder, on_done,
        password=False, allow_placeholder=True, validate=None,
        initial_value: str = "",
    ) -> _View:
        def builder() -> list[Static]:
            self._pending_input = _PendingInput(
                on_done=on_done,
                placeholder=placeholder,
                allow_placeholder=allow_placeholder,
                validate=validate,
            )
            return steps.input_body(
                title,
                subtitle,
                placeholder,
                password,
                initial_value=initial_value,
            )
        return _View(step, builder)

    def _goto_input(self, step, title, subtitle, *, placeholder, on_done,
                    password=False, allow_placeholder=True, validate=None,
                    initial_value: str = "") -> None:
        self._goto(self._input_view(
            step, title, subtitle, placeholder=placeholder,
            on_done=on_done, password=password,
            allow_placeholder=allow_placeholder, validate=validate,
            initial_value=initial_value,
        ))

__all__ = ["OnboardWizardApp"]
