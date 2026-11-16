"""Socket-shaped, bounded JSON byte transport over Windows named pipes.

Only bytes cross multiprocessing connections: never unpickle a local peer.
POSIX callers retain their existing Unix socket and its latency profile.
"""

from __future__ import annotations

import os
import socket
import time

from yoke_contracts.hook_evaluator_protocol import MAX_FRAME_BYTES


def uses_named_pipe() -> bool:
    return os.name == "nt"


class PipePeer:
    """Adapt message-mode pipes to the existing length-prefixed wire protocol."""

    def __init__(self, peer):
        self.peer = peer
        self.buffer = b""
        self.deadline = None

    def settimeout(self, seconds):
        self.deadline = None if seconds is None else time.monotonic() + seconds

    def _remaining(self):
        return (
            None if self.deadline is None else max(0, self.deadline - time.monotonic())
        )

    def sendall(self, data):
        self._bounded(lambda: self.peer.send_bytes(data))

    def _bounded(self, operation):
        import queue
        import threading

        result = queue.Queue(maxsize=1)

        def run():
            try:
                result.put((True, operation()))
            except (OSError, EOFError) as exc:
                result.put((False, exc))

        threading.Thread(target=run, daemon=True).start()
        try:
            success, value = result.get(timeout=self._remaining())
        except queue.Empty:
            self.close()
            raise socket.timeout("resident pipe I/O budget exhausted") from None
        if not success:
            raise value
        return value

    def recv(self, size):
        if not self.buffer:
            if not self.peer.poll(self._remaining()):
                raise socket.timeout(
                    "resident pipe did not answer inside the hook budget"
                )
            try:
                self.buffer = self._bounded(
                    lambda: self.peer.recv_bytes(MAX_FRAME_BYTES + 4)
                )
            except EOFError:
                return b""
        result, self.buffer = self.buffer[:size], self.buffer[size:]
        return result

    def close(self):
        self.peer.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def connect_pipe(address: str, deadline: float) -> PipePeer:
    import queue
    import threading
    from multiprocessing import connection

    # Client's AF_PIPE busy retry can wait 20 seconds. Bound that wait in a
    # daemon and close a late connection so it never survives the caller.
    result = queue.Queue(maxsize=1)
    abandoned = threading.Event()

    def connect():
        try:
            peer = PipePeer(connection.Client(address, family="AF_PIPE"))
        except OSError as exc:
            result.put(exc)
            return
        result.put(peer)
        if abandoned.is_set():
            peer.close()

    threading.Thread(target=connect, daemon=True).start()
    try:
        peer = result.get(timeout=max(0, deadline - time.monotonic()))
    except queue.Empty:
        abandoned.set()
        try:
            late = result.get_nowait()
        except queue.Empty:
            pass
        else:
            if isinstance(late, PipePeer):
                late.close()
        raise socket.timeout("resident pipe connect budget exhausted") from None
    if isinstance(peer, OSError):
        raise peer
    return peer
