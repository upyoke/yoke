"""SSH host output stays inspectable when it is not valid UTF-8."""

from pathlib import Path
import sys

from yoke_harness.ssh_mac_transport import SshMacTransport


def test_remote_output_preserves_invalid_bytes_as_escapes():
    transport = object.__new__(SshMacTransport)
    transport._key_path = Path("unused")
    transport._host = "unused"
    transport._user = "unused"
    transport._ssh_argv = lambda _command: [
        sys.executable,
        "-c",
        "import os; os.write(1, b'before\\xe2'); os.write(1, b'after')",
    ]
    result = transport._run("ignored")
    assert result.returncode == 0
    assert result.stdout == "before\\xe2after"
