"""Team-server discovery selects company sign-in or machine admission."""

from yoke_cli.config import team_server_authorization
from yoke_cli.config.onboard_wizard_flow_machine_admission import (
    MachineAdmissionChoiceFlow,
)
from yoke_cli.config.onboard_wizard_self_host import NO_SERVER_GUIDANCE
from yoke_cli.config.onboard_wizard_widgets import STEP_CONNECT
from yoke_cli.config.setup_prompt import SelectionRow


class TeamServerConnectFlow(MachineAdmissionChoiceFlow):
    def _goto_team_server(self):
        self._goto_input(
            "connect.team_server_url",
            STEP_CONNECT,
            "Connect to your team server.",
            self._machine_admission_notice()
            + " Enter its URL. Yoke checks how this machine can join your team. "
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
                self._goto_machine_admission()

        self._run_checking(
            step=STEP_CONNECT,
            title="Checking company sign-in.",
            message="Reading the sign-in method configured by your server.",
            detail_lines=[self._machine_admission_notice()],
            work=lambda: team_server_authorization.browser_sign_in_available(url),
            on_success=success,
            on_error=lambda exc: self._goto_yoke_verify_error(str(exc), "team-server"),
            group="onboard-team-server-method",
        )

    def _team_server_error_rows(self):
        return [
            SelectionRow(
                "token",
                "Use API token",
                "use an existing credential for first boot or recovery",
            ),
            SelectionRow("retry", "Edit connection", "check the server URL and retry"),
            SelectionRow("back", "Choose another home", "return to destinations"),
        ]

    def _connection_verify_error_rows(self, retry_source):
        if retry_source == "team-server":
            return self._team_server_error_rows()
        return [
            SelectionRow("retry", "Edit connection", "return to the populated form"),
            SelectionRow("back", "Choose another home", "return to destinations"),
        ]
