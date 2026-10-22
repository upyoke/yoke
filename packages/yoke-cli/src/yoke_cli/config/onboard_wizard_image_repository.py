"""Self-host preview and repository selection using the shared wizard input."""

from yoke_cli.config import server_image_repository as repository
from yoke_cli.config import onboard_docker_prerequisites as docker
from yoke_cli.config.onboard_wizard_widgets import STEP_CONNECT
from yoke_cli.config.setup_prompt import TONE_ERROR, SelectionRow, SetupPrompt


def preview_lines(setup) -> list[str]:
    return [
        f"Docker Compose · local-only URL {setup.url}",
        f"Files: {setup.directory}",
        f"Image repository: {setup.image_repository}",
        *(
            [
                "Existing bundle: Start restarts it and reconnects this machine "
                "with its first-boot admin token."
            ]
            if setup.bundle_created
            else [
                "Start asks your name: first boot makes you this server's first admin.",
                "Start writes the bundle and privately hands host-opened secrets to Docker.",
            ]
        ),
        *docker.preparation_guidance(),
        "You own reachable networking and TLS for team access.",
    ]


def prompt(shell, setup) -> None:
    from yoke_cli.config.onboard_wizard_self_host import goto_self_host_server

    def selected(value: str) -> None:
        setup.image_repository = repository.validate(value)
        goto_self_host_server(shell)

    shell._goto_input(
        "connect.image_repository",
        STEP_CONNECT,
        "Choose the server image repository.",
        "Use a fork, mirror, or private registry that carries the release's commit tags.",
        placeholder=setup.image_repository,
        initial_value=setup.image_repository,
        validate=_input_error,
        on_done=selected,
    )


def _input_error(value: str) -> str | None:
    try:
        repository.validate(value)
    except ValueError as exc:
        return str(exc)
    return None


def load_setup(shell):
    from yoke_cli.config import onboard_self_host_server as server
    from yoke_cli.config.onboard_wizard_state import _View

    try:
        return server.new_setup(config_path=shell.result.config_path)
    except ValueError as exc:
        message = str(exc)
        shell._goto(
            _View(
                SetupPrompt(
                    key="connect.load_setup",
                    step=STEP_CONNECT,
                    title="Self-host image configuration needs attention.",
                    message=message,
                    choices=tuple([SelectionRow("back", "Back", "repair the named machine setting")]),
                    tone=TONE_ERROR,
                ),
                lambda _choice: shell._step_back(),
            )
        )
        return None
