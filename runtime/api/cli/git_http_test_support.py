"""Real smart HTTP Git with a fixture credential, confined to loopback."""

from contextlib import contextmanager
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import threading
from urllib.parse import urlsplit

FIXTURE_CREDENTIAL = "fixture:own-credential"
# Real Git starts helpers and a smart-HTTP backend under full-suite CPU load.
# Short deadline behavior belongs to the separate process-boundary tests.
GIT_OPERATION_TIMEOUT_SECONDS = 60
_BACKEND_TIMEOUT_SECONDS = 30


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
        timeout=GIT_OPERATION_TIMEOUT_SECONDS,
    ).stdout.strip()


@contextmanager
def authenticated_remote(tmp_path):
    remote = tmp_path / "repo.git"
    subprocess.run(
        ["git", "init", "--bare", str(remote)],
        check=True,
        capture_output=True,
        timeout=GIT_OPERATION_TIMEOUT_SECONDS,
    )
    git(remote, "config", "http.receivepack", "true")
    expected = "Basic " + base64.b64encode(FIXTURE_CREDENTIAL.encode()).decode()
    requests = []
    failures = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            self.serve_git()

        def do_POST(self):
            self.serve_git()

        def serve_git(self):
            try:
                self.serve_git_request()
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                failures.append(repr(exc))
                self.send_error(500, "fixture Git backend failed")

        def serve_git_request(self):
            self.connection.settimeout(_BACKEND_TIMEOUT_SECONDS)
            authorized = self.headers.get("Authorization") == expected
            requests.append(authorized)
            if not authorized:
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="fixture"')
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            url = urlsplit(self.path)
            length = int(self.headers.get("Content-Length", "0"))
            result = subprocess.run(
                ["git", "http-backend"],
                input=self.rfile.read(length),
                capture_output=True,
                check=True,
                timeout=_BACKEND_TIMEOUT_SECONDS,
                env={
                    **os.environ,
                    "GIT_PROJECT_ROOT": str(tmp_path),
                    "GIT_HTTP_EXPORT_ALL": "1",
                    "REQUEST_METHOD": self.command,
                    "PATH_INFO": url.path,
                    "QUERY_STRING": url.query,
                    "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                    "CONTENT_LENGTH": str(length),
                    "REMOTE_USER": "fixture",
                },
            )
            headers, body = result.stdout.split(b"\r\n\r\n", 1)
            lines = [line.decode().split(": ", 1) for line in headers.split(b"\r\n")]
            status = next((int(v.split()[0]) for k, v in lines if k == "Status"), 200)
            self.send_response(status)
            for key, value in lines:
                if key != "Status":
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    # Join bounded request handlers before inspecting their failures at teardown.
    server.daemon_threads = False
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/repo.git", remote, requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        assert not failures, f"Authenticated Git fixture failed: {failures}"


def own_credential_config(root: Path, url: str):
    credential = root / "git-credentials"
    endpoint = urlsplit(url)
    credential.write_text(f"http://{FIXTURE_CREDENTIAL}@{endpoint.netloc}\n")
    config = root / "gitconfig"
    config.write_text(f"[credential]\n\thelper = store --file={credential}\n")
    return config
