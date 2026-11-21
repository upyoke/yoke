"""Exercise the resident wire protocol over the platform's real transport."""

from contextlib import contextmanager
from pathlib import Path
import socket
import tempfile
import time

from yoke_contracts.machine_config import reader as machine_config
from yoke_contracts.hook_resident_paths import resident_paths
from yoke_cli.hook_resident_client import _connect
from yoke_contracts.hook_resident_transport import PipePeer, uses_named_pipe
from yoke_contracts.machine_config.directories import shortest_temp_directory


@contextmanager
def resident_test_paths(monkeypatch):
    # Keep AF_UNIX addresses below macOS's bound; Windows gets the product pipe.
    with tempfile.TemporaryDirectory(prefix="yhr-", dir=shortest_temp_directory()) as directory:
        with monkeypatch.context() as patch:
            patch.setattr(machine_config, "cache_dir", lambda: Path(directory))
            yield resident_paths()


@contextmanager
def resident_listener(paths):
    if uses_named_pipe():
        from multiprocessing.connection import Listener

        listener = Listener(str(paths.socket), family="AF_PIPE")
    else:
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(paths.socket))
        listener.listen(8)
    try:
        yield listener
    finally:
        listener.close()


def accept_peer(listener):
    if uses_named_pipe():
        return PipePeer(listener.accept())
    return listener.accept()[0]


def connect_peer(paths, timeout=5):
    peer = _connect(paths, time.monotonic() + timeout)
    peer.settimeout(timeout)
    return peer
