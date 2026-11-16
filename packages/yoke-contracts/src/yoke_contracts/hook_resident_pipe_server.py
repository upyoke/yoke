"""Polling threaded accept loop for the Windows resident named pipe."""

import queue
import socketserver
import threading

from yoke_contracts.hook_resident_transport import PipePeer


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
        while not self.closed.is_set():
            try:
                peer = PipePeer(self.listener.accept())
            except OSError as exc:
                if not self.closed.is_set():
                    self.incoming.put(exc)
                return
            if self.closed.is_set():
                peer.close()
            else:
                self.incoming.put(peer)

    def handle_request(self):
        try:
            peer = self.incoming.get(timeout=self.timeout)
        except queue.Empty:
            return
        if isinstance(peer, OSError):
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
