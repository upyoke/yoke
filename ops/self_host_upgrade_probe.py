"""Exercise the production upgrade function from the installed candidate wheel."""

from importlib.metadata import version
from pathlib import Path
import sys

from yoke_cli.config.install_binding import detect, KIND_PACKAGED_WHEEL
from yoke_cli.self_host import bundle, release_target, upgrade


def main() -> None:
    directory, image, sha, installer = sys.argv[1:]
    assert detect()["kind"] == KIND_PACKAGED_WHEEL
    target = release_target.ReleaseTarget(
        version=version("yoke-cli"),
        source_commit=sha,
        image=image,
        base_url="http://localhost:5200",
        channel="probe",
        installer_url=Path(installer).as_uri(),
    )
    plan = upgrade.UpgradePlan(
        directory=Path(directory),
        target=target,
        docker_executable="docker",
        previous_image=image,
    )
    assert upgrade.execute_upgrade(plan)["ok"] is True
    bundle.validate_existing_bundle(directory=directory)


if __name__ == "__main__":
    main()
