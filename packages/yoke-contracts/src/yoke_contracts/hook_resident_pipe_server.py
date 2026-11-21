"""Polling threaded accept loop for the Windows resident named pipe."""

import queue
import socketserver
import sys
import threading

from yoke_contracts.hook_resident_transport import PipePeer

#: Consecutive accept failures after which the resident exits.
MAX_ACCEPT_FAILURES = 5
ACCEPT_RETRY_SECONDS = 0.1


class PipeServer(socketserver.ThreadingMixIn, socketserver.BaseServer):
    """Accept named pipes off the polling thread; drain requests as on POSIX."""

    daemon_threads = True
    block_on_close = False

    def __init__(self, address, handler):
        from multiprocessing import connection

        super().__init__(address, handler)
        self.listener = connection.Listener(address, family="AF_PIPE")
        self.incoming = queue.Queue()
        self.closed = threading.Event()
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        # One failed accept (a client that abandoned the pipe mid-connect, or
        # CPython's ``assert err == 0`` in ``PipeListener.accept``) must not
        # end accepting. Only a listener that keeps failing ends the resident,
        # and the next hook's cold start replaces it.
        failures = 0
        while not self.closed.is_set():
            try:
                peer = PipePeer(self.listener.accept())
            except Exception as exc:
                if self.closed.is_set():
                    return
                failures += 1
                sys.stderr.write(
                    f"yoke hook resident: pipe accept failed "
                    f"({failures}/{MAX_ACCEPT_FAILURES}): {exc!r}\n"
                )
                if failures >= MAX_ACCEPT_FAILURES:
                    self.incoming.put(exc)
                    return
                self.closed.wait(ACCEPT_RETRY_SECONDS)
                continue
            failures = 0
            if self.closed.is_set():
                peer.close()
            else:
                self.incoming.put(peer)

    def handle_request(self):
        try:
            peer = self.incoming.get(timeout=self.timeout)
        except queue.Empty:
            return
        if isinstance(peer, Exception):
            raise peer
        self.process_request(peer, self.server_address)

    def shutdown_request(self, request):
        request.close()

    def server_close(self):
        self.closed.set()
        self.listener.close()
        while not self.incoming.empty():
            peer = self.incoming.get_nowait()
            if isinstance(peer, PipePeer):
                peer.close()
