"""Give Windows SSH a private regular input stream instead of a feeder pipe."""

import os
from pathlib import Path
import subprocess
import tempfile

from yoke_contracts.owner_private_path import (
    create_owner_private_directory,
    write_owner_private,
)


WINDOWS_CONTROLLER = os.name == "nt"


def run_ssh(argv, *, input_text=None, **kwargs):
    if not WINDOWS_CONTROLLER or input_text is None:
        return subprocess.run(argv, input=input_text, **kwargs)
    # Protect password-bearing frames before writing; inherited TEMP ACLs
    # are not sufficient. Close the child and stream before deleting custody.
    with tempfile.TemporaryDirectory(prefix="yoke-ssh-stdin-") as temporary:
        private = create_owner_private_directory(Path(temporary) / "private")
        path = private / "frame"
        write_owner_private(path, input_text.encode("ascii"))
        with path.open("rb") as source:
            return subprocess.run(argv, stdin=source, **kwargs)
