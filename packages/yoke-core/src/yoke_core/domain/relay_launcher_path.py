"""Choose a local or served-release relay launcher path."""
from pathlib import Path
from yoke_core.domain.relay_release_path import relay_launch_executable
from yoke_core.domain import local_relay_launcher_path as local_install

def relay_launcher_path(state_dir: Path, *, follows_served_release: bool) -> Path:
    """The absolute executable launchd runs for one relay.

    Pure and total: a machine that has not installed its launcher yet still
    resolves to a path, so the launchd document stays computable and the
    refusal is raised where it can be recovered.
    """
    if follows_served_release:
        return relay_launch_executable(state_dir)
    return local_install.local_launcher_path()

