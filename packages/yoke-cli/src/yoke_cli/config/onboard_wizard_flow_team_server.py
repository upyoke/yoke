"""Team-server URL discovery precedes choosing browser or token sign-in."""

from yoke_cli.config import team_server_authorization, onboard_wizard_steps as steps
from yoke_cli.config.onboard_wizard_self_host import NO_SERVER_GUIDANCE
from yoke_cli.config.onboard_wizard_widgets import STEP_CONNECT, SelectionRow


class TeamServerConnectFlow:
    def _goto_team_server(self):
        self._goto_input(
            STEP_CONNECT,
            "Connect to your team server.",
            "Enter its URL. Yoke checks whether your team uses company sign-in or API tokens. "
            + NO_SERVER_GUIDANCE,
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

    def _team_server_error_rows(self):
        return [
            SelectionRow("token", "Use API token", "connect without company sign-in"),
            SelectionRow("retry", "Edit connection", "check the server URL and retry"),
            SelectionRow("back", "Choose another home", "return to destinations"),
        ]

    def _connection_verify_error_rows(self, retry_source):
        if retry_source == "team-server":
            return self._team_server_error_rows()
        if retry_source == "server-form":
            return [
                SelectionRow(
                    "retry", "Edit connection", "return to the populated form"
                ),
                SelectionRow("back", "Choose another home", "return to destinations"),
            ]
        return steps.YOKE_TOKEN_VERIFY_RETRY_ROWS
