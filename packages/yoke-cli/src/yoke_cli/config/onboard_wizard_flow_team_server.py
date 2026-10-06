"""Team-server URL discovery precedes choosing browser or token sign-in."""

from yoke_cli.config import team_server_authorization
from yoke_cli.config.onboard_wizard_widgets import STEP_CONNECT


class TeamServerConnectFlow:
    def _goto_team_server(self):
        self._goto_input(
            STEP_CONNECT,
            "Connect to your team server.",
            "Enter its URL. Yoke checks whether your team uses company sign-in or API tokens.",
            placeholder=self.result.api_url or "https://api.mycompany.com",
            allow_placeholder=bool(self.result.api_url),
            on_done=self._discover_team_server,
        )

    def _discover_team_server(self, url):
        self.result.api_url = url

        def success(enabled):
            if enabled:
                self._machine_authorization_server = url
                self._start_hosted_machine_authorization()
            else:
                self._machine_authorization_server = None
                self._goto_server_connection_form()

        self._run_checking(
            step=STEP_CONNECT,
            title="Checking company sign-in.",
            message="Reading the sign-in method configured by your server.",
            work=lambda: team_server_authorization.browser_sign_in_available(url),
            on_success=success,
            on_error=lambda exc: self._goto_yoke_verify_error(str(exc), "team-server"),
            group="onboard-team-server-method",
        )
