"""Deployment-destination picker for the ``yoke onboard`` wizard.

A mixin composed into :class:`onboard_wizard_app.OnboardWizardApp` in front
of :class:`onboard_wizard_flow_connect.ConnectFlow`. It opens the Account
step with one question — where should this Yoke live: this machine, a team
server, or upyoke.com — and routes to the matching sign-in lane. The answer
changes only that lane:

* **This machine** replaces sign-in entirely — the local universe is born
  at Apply by the existing ``local_universe_setup`` machinery, so the
  Account step becomes a universe summary instead of a token prompt.
* **A team server** collects the server URL, then the API token.
* **upyoke.com** picks the hosted environment, then the API token.

PATH, machine GitHub, project, review, apply, and resume stay
destination-independent; every lane continues in :class:`ConnectFlow` /
:class:`onboard_wizard_flow.WizardFlow` from ``_goto_machine_github``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from yoke_cli.config import onboard_wizard_steps as steps
from yoke_cli.config.local_universe_setup import LOCAL_ENV
from yoke_cli.config.onboard_destinations import (
    DEFAULT_DESTINATION,
    DEFAULT_SIGN_IN_ENV,
    DESTINATION_HOSTED,
    DESTINATION_LOCAL,
    DESTINATION_SERVER,
    is_hosted_url,
)
from yoke_cli.config.onboard_wizard_palette import BRAND
from yoke_cli.config.onboard_wizard_widgets import (
    STEP_CONNECT,
    STEP_CONNECT_LABEL,
    SelectionRow,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_cli.config.onboard_wizard_app import _View

# Where should this Yoke live? Every row is a full first-class deployment of
# the same engine; the hint names what makes each home different.
DESTINATION_ROWS = [
    SelectionRow(DESTINATION_LOCAL, "This machine",
                 "free · no account · stays here"),
    SelectionRow(DESTINATION_SERVER, "A team server",
                 "your own Yoke server URL"),
    SelectionRow(DESTINATION_HOSTED, "upyoke.com", "hosted by Yoke"),
]
_DEFAULT_DESTINATION_INDEX = next(
    index for index, row in enumerate(DESTINATION_ROWS)
    if row.value == DEFAULT_DESTINATION
)

# Rail label per destination: the sign-in destinations keep the Account
# label; a local run's Account step is universe setup, not sign-in.
ACCOUNT_STEP_LABELS = {
    DESTINATION_LOCAL: "Universe",
    DESTINATION_SERVER: STEP_CONNECT_LABEL,
    DESTINATION_HOSTED: STEP_CONNECT_LABEL,
}


class _Shell(Protocol):  # pragma: no cover - structural typing only
    result: Any
    _account_step_label: str
    _destination_preset: bool

    def _goto(self, view: "_View") -> None: ...
    def _selection_view(self, step, title, subtitle, rows, on_select,
                        *, initial: int = 0) -> "_View": ...
    def _goto_input(self, step, title, subtitle, *, placeholder, on_done,
                    password: bool = False,
                    allow_placeholder: bool = True,
                    initial_value: str = "") -> None: ...
    def _goto_machine_github(self) -> None: ...
    def _goto_token_source(self) -> None: ...
    def _goto_hosted_env_select(self) -> None: ...
    def _after_api_url(self, value: str) -> None: ...


class DestinationFlow:
    def _start_connect(self: _Shell) -> None:
        if self._destination_preset:
            self._route_destination(self.result.destination)
            return
        if self.result.api_url:
            # A stored connection already names this machine's destination;
            # route straight to its lane (the rerun convenience path — the
            # stored token verify still runs before anything is reused).
            self._route_destination(
                DESTINATION_HOSTED if is_hosted_url(self.result.api_url)
                else DESTINATION_SERVER
            )
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
                initial=_DEFAULT_DESTINATION_INDEX,
            )

        self._account_step_label = STEP_CONNECT_LABEL
        self._goto(_View(STEP_CONNECT, builder, self._after_destination_select))

    def _after_destination_select(self: _Shell, choice: str) -> None:
        self._route_destination(choice)

    def _route_destination(self: _Shell, choice: str) -> None:
        self.result.destination = choice
        self._account_step_label = ACCOUNT_STEP_LABELS.get(
            choice, STEP_CONNECT_LABEL,
        )
        if choice == DESTINATION_LOCAL:
            self._prepare_local_result()
            self._goto_local_universe_summary()
            return
        if self.result.env_name == LOCAL_ENV:
            # A local detour left the local env label behind; sign-in lanes
            # never use it (the hosted select re-picks its own env id).
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
        if is_hosted_url(self.result.api_url):
            self._goto_token_source()
            return
        self.result.api_url = ""
        self._goto_hosted_env_select()

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

        self._goto(_View(
            STEP_CONNECT,
            lambda: steps.verification_body(
                "Your Yoke lives on this machine.",
                "Free, no account — everything stays on this computer.",
                [
                    "Apply creates a private local universe under ~/.yoke "
                    "(embedded Postgres, the full Yoke schema).",
                    "Same engine as a team server or upyoke.com — move "
                    "later with a dump and restore.",
                ],
                steps.VERIFY_OK_ROWS,
                ok=True,
            ),
            lambda _choice: self._goto_machine_github(),
        ))

    # ── server destination: URL, then token ─────────────────

    def _goto_server_url_input(self: _Shell) -> None:
        self._goto_input(
            STEP_CONNECT, f"Enter your {BRAND} server URL.",
            "Where your team's Yoke lives — e.g. https://api.mycompany.com.",
            placeholder="https://api.mycompany.com",
            allow_placeholder=False,
            on_done=self._after_api_url,
        )


__all__ = [
    "ACCOUNT_STEP_LABELS",
    "DESTINATION_ROWS",
    "DestinationFlow",
]
