"""Deployment-destination picker for the ``yoke onboard`` wizard.

This mixin opens the Account step with one question — where should this Yoke
live — and routes to the matching connection lane:

* **This machine** replaces sign-in entirely — the local universe is born
  at Apply by the existing ``local_universe_setup`` machinery, so the
  Account step becomes a universe summary instead of a token prompt.
* **A team server** collects a URL/token or guides a local Compose first boot.
* **upyoke.com** picks the hosted environment, then starts browser approval.

Every lane rejoins the destination-independent flow at ``_goto_machine_github``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from yoke_cli.config import local_universe_setup
from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config.local_universe_setup import LOCAL_ENV
from yoke_cli.config.onboard_destinations import (
    DEFAULT_SIGN_IN_ENV,
    DESTINATION_HOSTED,
    DESTINATION_LOCAL,
    DESTINATION_SERVER,
    hosted_environment_for_url,
    is_hosted_url,
)
from yoke_cli.config.onboard_destination_rows import (
    ACCOUNT_STEP_LABELS,
    DEFAULT_DESTINATION_INDEX,
    DESTINATION_ROWS,
    HOSTED_ROW_ENVS,
    SELF_HOST_SERVER_ROW,
)
from yoke_cli.config.onboard_wizard_local_universe_summary import (
    local_universe_summary_lines,
    local_universe_summary_rows,
)
from yoke_cli.config.onboard_wizard_self_host import (
    NO_SERVER_GUIDANCE,
    goto_self_host_server,
)
from yoke_cli.config.onboard_wizard_palette import BRAND
from yoke_cli.config.onboard_wizard_widgets import (
    STEP_CONNECT,
    STEP_CONNECT_LABEL,
    SelectionRow,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.onboard_wizard_app import _View

_STORED_DESTINATION = "stored"


class _Shell(Protocol):  # pragma: no cover - structural typing only
    result: Any
    _history: list[Any]
    _account_step_label: str
    _destination_preset: bool
    _api_url_preset: bool
    _stored_yoke_token_available: bool

    def _goto(self, view: "_View") -> None: ...
    def _selection_view(
        self, step, title, subtitle, rows, on_select, *, initial: int = 0
    ) -> "_View": ...
    def _goto_input(
        self,
        step,
        title,
        subtitle,
        *,
        placeholder,
        on_done,
        password: bool = False,
        allow_placeholder: bool = True,
        initial_value: str = "",
    ) -> None: ...
    def _goto_machine_github(self) -> None: ...
    def _goto_token_source(self) -> None: ...
    def _start_hosted_machine_authorization(self) -> None: ...
    def _after_api_url(self, value: str) -> None: ...
    def _render_current(self) -> None: ...


class DestinationFlow:
    def _start_connect(self: _Shell) -> None:
        if self._destination_preset:
            self._route_destination(self.result.destination)
            return
        if self._api_url_preset and self.result.api_url:
            self._route_destination(
                DESTINATION_HOSTED
                if is_hosted_url(self.result.api_url)
                else DESTINATION_SERVER
            )
            return
        if self._stored_yoke_token_available and self.result.api_url:
            self._goto_stored_destination_picker()
            return
        self._goto_destination_picker()

    def _goto_destination_picker(self: _Shell) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        def builder() -> list:
            # Runs on every render of this view — including an Esc-back from
            # a destination lane — so the rail label always reads as the
            # undecided Account step while the picker is on screen.
            self._account_step_label = STEP_CONNECT_LABEL
            return steps.selection_body(
                "Where should this Yoke live?",
                "Every home runs the full engine — you can add another later.",
                DESTINATION_ROWS,
                initial=DEFAULT_DESTINATION_INDEX,
            )

        self._account_step_label = STEP_CONNECT_LABEL
        view = _View(STEP_CONNECT, builder, self._after_destination_select)
        self._destination_picker_view = view
        self._goto(view)

    def _goto_stored_destination_picker(self: _Shell) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        stored_destination = (
            DESTINATION_HOSTED
            if is_hosted_url(self.result.api_url)
            else DESTINATION_SERVER
        )
        env = str(self.result.env_name or DEFAULT_SIGN_IN_ENV)
        label = (
            f"Use existing hosted {env} connection"
            if stored_destination == DESTINATION_HOSTED
            else f"Use existing {env} server connection"
        )
        # The URL names the connection in the subtitle, where it can wrap; a
        # row hint is cut to the room beside its label, which would hide the
        # organization at the end of a hosted URL on an 80-column terminal.
        rows = [
            SelectionRow(_STORED_DESTINATION, label, "saved in machine config"),
            *DESTINATION_ROWS,
        ]
        api_url = self.result.api_url

        def builder() -> list:
            self._account_step_label = STEP_CONNECT_LABEL
            return steps.selection_body(
                "Use this saved Yoke connection?",
                f"Yoke found {api_url} in machine config. Reuse it, or choose "
                "another home.",
                rows,
            )

        self._account_step_label = STEP_CONNECT_LABEL
        view = _View(
            STEP_CONNECT,
            builder,
            lambda choice: self._after_stored_destination_select(
                choice,
                stored_destination,
            ),
        )
        self._destination_picker_view = view
        self._goto(view)

    def _after_destination_select(self: _Shell, choice: str) -> None:
        self._route_destination(choice)

    def _after_stored_destination_select(
        self: _Shell,
        choice: str,
        stored_destination: str,
    ) -> None:
        if choice == _STORED_DESTINATION:
            self._route_destination(stored_destination)
            return
        self._clear_stored_connection()
        self._route_destination(choice)

    def _clear_stored_connection(self: _Shell) -> None:
        self.result.api_url = ""
        self.result.token = None
        self.result.token_file = None
        self.result.token_source_kind = "prompt"
        self.result.yoke_token_verification = None
        self._stored_yoke_token_available = False

    def _route_destination(self: _Shell, choice: str) -> None:
        if choice == SELF_HOST_SERVER_ROW:
            self.result.destination = DESTINATION_SERVER
            self._account_step_label = STEP_CONNECT_LABEL
            goto_self_host_server(self)
            return
        hosted_env = HOSTED_ROW_ENVS.get(choice)
        if choice == DESTINATION_HOSTED and self._api_url_preset:
            # ``--connect`` resolves both hosted platform URLs to the shared
            # destination id. Preserve the environment carried by that exact
            # URL instead of treating the id as the production picker row.
            hosted_env = hosted_environment_for_url(self.result.api_url) or hosted_env
        # The hosted rows are one destination reached through two platforms;
        # the row is the environment choice.
        self.result.destination = (
            DESTINATION_HOSTED if hosted_env is not None else choice
        )
        self._account_step_label = ACCOUNT_STEP_LABELS.get(
            choice,
            STEP_CONNECT_LABEL,
        )
        if choice == DESTINATION_LOCAL:
            self._prepare_local_result()
            self._goto_local_universe_summary()
            return
        if hosted_env is None and self.result.env_name == LOCAL_ENV:
            # A local detour left the local env label behind; the team-server
            # lane never uses it.
            self.result.env_name = DEFAULT_SIGN_IN_ENV
        if choice == DESTINATION_SERVER:
            if self.result.api_url and not is_hosted_url(self.result.api_url):
                self._goto_token_source()
                return
            # A hosted URL left behind by an earlier hosted visit is not a
            # team server; collect the real one.
            self.result.api_url = ""
            self._goto_server_url_input()
            return
        if is_hosted_url(self.result.api_url) and self._stored_yoke_token_available:
            # A previously browser-approved connection may reuse its owner-only
            # machine credential. A URL preset such as ``--connect
            # https://app.upyoke.com`` is not credential authority and must
            # start a fresh browser approval instead of exposing token entry.
            self._goto_token_source()
            return
        # Only a fresh approval takes the row's environment. A reused stored
        # connection keeps the env label it was approved under — that is the
        # org slug the credential belongs to, not a platform name.
        self.result.env_name = hosted_env or DEFAULT_SIGN_IN_ENV
        self._clear_stored_connection()
        self._start_hosted_machine_authorization()

    # ── local destination: universe setup replaces sign-in ──

    def _prepare_local_result(self: _Shell) -> None:
        # Local mode has no sign-in: no API URL, no token. Clear anything a
        # stored connection hydrated or an earlier hosted/server visit
        # recorded so the collected field set reads as the local lane.
        self.result.env_name = LOCAL_ENV
        self.result.api_url = ""
        self.result.token = None
        self.result.token_file = None
        self.result.token_source_kind = "prompt"
        self.result.yoke_token_verification = None

    def _goto_local_universe_summary(self: _Shell) -> None:
        from yoke_cli.config.onboard_wizard_app import _View

        state = local_universe_setup.inspect_local_state(self.result.config_path)
        rows = local_universe_summary_rows(state)

        self._goto(
            _View(
                STEP_CONNECT,
                lambda: steps.verification_body(
                    "Your Yoke lives on this machine.",
                    "Free, no account — everything stays on this computer.",
                    local_universe_summary_lines(state),
                    rows,
                    ok=state.get("state")
                    != local_universe_setup.LOCAL_UNIVERSE_UNAVAILABLE,
                ),
                self._on_local_universe_summary,
            )
        )

    def _on_local_universe_summary(self: _Shell, choice: str) -> None:
        if choice != "back":
            self._goto_machine_github()
            return
        self._return_to_destination_picker()

    def _return_to_destination_picker(
        self: _Shell, *, drop_current: bool = True,
    ) -> None:
        """Land on the picker this run showed, or open one when none was shown.

        A lane that passed through the picker unwinds history back to it, so
        the rail and the picker's own re-render rules apply. A preset run
        never showed one; ``drop_current`` removes the view asking to leave
        (a summary or error view) before a fresh picker is pushed, and is
        False when the caller already popped its view (a cancelled check).
        """
        target = getattr(self, "_destination_picker_view", None)
        for index in range(len(self._history) - 1, -1, -1):
            if self._history[index] is target:
                del self._history[index + 1 :]
                self._render_current()
                return
        if drop_current and self._history:
            self._history.pop()
        self._goto_destination_picker()

    # ── server destination: URL, then token ─────────────────
    def _goto_server_url_input(self: _Shell) -> None:
        self._goto_input(
            STEP_CONNECT,
            f"Enter your {BRAND} server URL.",
            "Where your team's Yoke lives — e.g. https://api.mycompany.com. "
            + NO_SERVER_GUIDANCE,
            placeholder="https://api.mycompany.com",
            allow_placeholder=False,
            on_done=self._after_api_url,
        )


__all__ = [
    "ACCOUNT_STEP_LABELS",
    "DESTINATION_ROWS",
    "DestinationFlow",
]
