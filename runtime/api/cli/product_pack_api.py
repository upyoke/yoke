"""Local typed-function API used by packaged CLI Pack proofs."""

import http.server
import json
import threading


class PackApi:
    def __init__(self) -> None:
        self.requests: list[dict[str, str]] = []
        self.url = ""
        self._server: http.server.ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "PackApi":
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                size = int(self.headers.get("Content-Length", "0"))
                request = json.loads(self.rfile.read(size).decode("utf-8"))
                owner.requests.append({
                    "method": "POST",
                    "path": self.path,
                    "authorization": self.headers.get("Authorization", ""),
                    "function": request.get("function", ""),
                    "project": request.get("payload", {}).get("project", ""),
                })
                if self.path != "/v1/functions/call":
                    self.send_error(404)
                    return
                self._send_json({
                    "success": True,
                    "function": request["function"],
                    "version": request["version"],
                    "request_id": request.get("request_id"),
                    "result": {
                        "project_id": 41,
                        "project_slug": "sample",
                        "repository_report": None,
                        "packs": [{
                            "slug": "webapp-scaffold",
                            "name": "Web Application Scaffold",
                            "description": "Generic application starting point.",
                            "latest_version": "1.0.0",
                            "dependencies": [],
                            "documentation": "docs/packs/webapp-scaffold/README.md",
                            "settings_schema": {},
                            "verification": [],
                            "file_count": 2,
                            "status": "available",
                            "installed_version": None,
                        }],
                    },
                })

            def log_message(self, format: str, *args: object) -> None:
                return

            def _send_json(self, payload: dict) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)


__all__ = ["PackApi"]
