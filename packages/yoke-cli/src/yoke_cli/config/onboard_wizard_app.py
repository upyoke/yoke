"""Textual shell for the fixed-frame, keyboard-driven onboarding wizard.

Per-step bodies and decision transitions live in focused sibling modules.
"""

from __future__ import annotations

from typing import Any, Callable

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widgets import Input, Rule, Static

from yoke_cli.config.onboard_terminal import (
    plain_glyphs,
    plain_text,
    screen_compat_terminal,
)
from yoke_cli.config import machine_config
from yoke_cli.config import onboard_destinations
from yoke_cli.config import onboard_project
from yoke_cli.config import onboard_wizard_chrome as chrome
from yoke_cli.config.onboard_wizard import (
    WizardDefaults,
    WizardResult,
    default_config_path,
)
from yoke_cli.config.onboard_wizard_body_scroll import BODY_ID, BodyScrollFlow
from yoke_cli.config.onboard_wizard_checking import CheckingFlow
from yoke_cli.config.onboard_wizard_copy_open import CopyOpenFlow
from yoke_cli.config.onboard_wizard_flow import WizardFlow
from yoke_cli.config.onboard_wizard_flow_apply import ApplyFlow
from yoke_cli.config.onboard_wizard_flow_board_art import BoardArtFlow
from yoke_cli.config.onboard_wizard_flow_clone import CloneFlow
from yoke_cli.config.onboard_wizard_flow_connect import ConnectFlow, HostedMachineConnectFlow
from yoke_cli.config.onboard_wizard_flow_destination import DestinationFlow
from yoke_cli.config.onboard_wizard_flow_dev import DevFlow
from yoke_cli.config.onboard_wizard_flow_github import MachineGithubFlow
from yoke_cli.config.onboard_wizard_flow_hosting import HostingFlow
from yoke_cli.config.onboard_wizard_flow_project_git import ProjectGitFlow
from yoke_cli.config.onboard_wizard_flow_publish import PublishFlow
from yoke_cli.config.onboard_wizard_flow_publish_manual import ManualPublishFlow
from yoke_cli.config.onboard_wizard_path import PathFlow
from yoke_cli.config.onboard_wizard_input_entry import InputEntry
from yoke_cli.config.onboard_wizard_state import _PendingForm, _PendingInput, _View
from yoke_cli.config.onboard_wizard_stored_connection import StoredConnectionHydration
from yoke_cli.config.onboard_wizard_view_helpers import ViewHelpers
from yoke_cli.config.onboard_wizard_widgets import (
    STEP_CONNECT_LABEL,
    SelectionList,
    Stepper,
)


class OnboardWizardApp(
    CheckingFlow, PathFlow, DestinationFlow, HostedMachineConnectFlow, ConnectFlow, MachineGithubFlow,
    ProjectGitFlow, WizardFlow, ApplyFlow, CloneFlow, DevFlow, ManualPublishFlow,
    PublishFlow, HostingFlow, BoardArtFlow, InputEntry, BodyScrollFlow,
    CopyOpenFlow, StoredConnectionHydration, ViewHelpers, App[None],
):
    CSS_PATH = "onboard_wizard.tcss"
    # The arrow bindings only reach the body when no list or input is focused:
    # a focused SelectionList sits earlier on the binding chain and keeps them.
    # The copy and open chords take priority so they still reach the shell from
    # a screen whose text box holds focus.
    BINDINGS = [
        Binding("escape", "back", "back", show=False),
        Binding("ctrl+[", "back", "back", show=False),
        Binding("ctrl+c", "quit_wizard", "quit", show=False, priority=True),
        Binding(chrome.COPY_KEY, "copy_target", "copy", show=False, priority=True),
        Binding(chrome.OPEN_KEY, "open_target", "open", show=False, priority=True),
        Binding("pageup", "body_page_up", "scroll up", show=False),
        Binding("pagedown", "body_page_down", "scroll down", show=False),
        Binding("up", "body_line_up", "scroll up", show=False),
        Binding("down", "body_line_down", "scroll down", show=False),
        Binding("home", "body_home", "top", show=False),
        Binding("end", "body_end", "bottom", show=False),
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
        self._stored_machine_github_api_url: str | None = None
        self._api_url_preset = bool(defaults.api_url)
        self._stored_project_attempted = False
        self._stored_project_checkouts: list[machine_config.ConfiguredProject] = []
        self._pending_stored_project_checkout: str | None = None
        self._project_mode_preset = defaults.project_mode is not None
        self._project_preset_attempted = False
        self._preset_dev_checkout: str | None = (
            defaults.project_checkout
            if defaults.project_mode == onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN
            else None
        )
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
            project_mode=(
                defaults.project_mode
                or onboard_project.PROJECT_MODE_MACHINE_ONLY
            ),
            project_checkout=defaults.project_checkout,
        )
        self._hydrate_stored_credentials(defaults)
        self._post_install = defaults.post_install
        self._history: list[_View] = []
        self._pending_input: _PendingInput | None = None
        self._pending_form: _PendingForm | None = None
        self._checking = False
        self._checking_blocks_quit = False
        # Set by ``_render_current`` and drained by the async message handlers so
        # the body swap runs in the same handler turn as the transition keypress.
        self._swap_pending = False
        # login -> github_publish.RepoOwner for the chosen publish owner picker.
        self._owner_lookup: dict[str, Any] = {}
        self._screen_compat = screen_compat_terminal()
        self._plain_glyphs = plain_glyphs()

    def compose(self) -> ComposeResult:
        yield Static(chrome.header(), id="onboard-header", markup=True)
        yield Stepper(id="onboard-stepper")
        yield self._divider()
        # Non-focusable: a scroll container that can take focus would steal it
        # from the active SelectionList/Input and leave Enter dead. Plain-glyph
        # terminals hide the scrollbar in the stylesheet and keep the keyboard
        # scroll keys.
        yield VerticalScroll(id=BODY_ID, can_focus=False)
        yield self._divider()
        yield Static(chrome.footer(), id="onboard-footer", markup=True)

    def _divider(self) -> Rule | Static:
        if self._screen_compat or self._plain_glyphs:
            return Static("", classes="onboard-divider")
        return Rule(classes="onboard-divider")

    async def on_mount(self) -> None:
        if self._plain_glyphs:
            self.screen.add_class("plain-glyphs")
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
        self._pending_form = None
        self._swap_pending = True
        body = self.query_one(f"#{BODY_ID}")
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
        body = self.query_one(f"#{BODY_ID}")
        # One frame for the whole swap: painting the emptied body and then the
        # new view as two frames lets the outgoing view's glyphs survive beside
        # the incoming ones on terminals without synchronized output. The new
        # view also starts at the top — a scroll offset carried over from a
        # taller view would draw a shorter one from its middle.
        with self.batch_update():
            await body.remove_children()
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
            # A FocusInput claims focus inside its own on_mount (so the first
            # key after the swap always lands); this re-asserts focus for the
            # SelectionList case and is idempotent for the input case.
            self._focus_first(widgets)
            # The copy and open keys act on whatever the incoming view shows,
            # so they are rebound with it rather than left pointing at the
            # screen the operator just left.
            self._set_copy_targets(view.copy_targets)

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

    async def action_back(self) -> None:
        if self._checking:
            # A check that named a cancel route (the browser-approval wait)
            # is abandoned and routes itself; any other check keeps Esc idle.
            if self._cancel_checking():
                await self._apply_pending_swap()
            return
        if len(self._history) > 1:
            self._pending_input = None
            self._pending_form = None
            self._history.pop()
            self._render_current()
            await self._apply_pending_swap()

    def action_quit_wizard(self) -> None:
        # Apply is an atomic worker-thread transaction that can't be killed mid-
        # flight; quitting here is the mid-mutation cliff (after clone, before
        # push) onboarding must avoid. Suppress quit while applying — the worker
        # finalizes the report and routes to success/failure, where Exit lives.
        if self._applying or self._checking_blocks_quit:
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

__all__ = ["OnboardWizardApp"]
