"""Local typed-function API used by packaged CLI Pack proofs."""

import hashlib
import http.server
import json
import threading


def _pack_bundle(version: str) -> dict:
    credentials_action = "aws-actions/configure-aws-credentials@immutable-sha"
    content = {
        "1.0.0": f"base\ncustom-slot\naction={credentials_action}\n",
        "1.1.0": f"base-v2\ncustom-slot\naction={credentials_action}\n",
    }[version]
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    files = [
        {
            "path": "sample-pack.txt",
            "content": content,
            "encoding": "utf-8",
            "sha256": digest,
            "mode": 0o644,
        }
    ]
    material = [
        {
            "path": "sample-pack.txt",
            "sha256": digest,
            "mode": 0o644,
            "encoding": "utf-8",
        }
    ]
    content_digest = hashlib.sha256(
        json.dumps(material, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "bundle_schema": 1,
        "project_id": 41,
        "project_slug": "sample",
        "pack": "sample-pack",
        "name": "Sample Pack",
        "description": "Packaged HTTPS transport fixture.",
        "version": version,
        "latest_version": "1.1.0",
        "dependencies": [],
        "render_values": {
            "configure_aws_credentials_action": credentials_action,
        },
        "files": files,
        "content_digest": content_digest,
    }


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
                owner.requests.append(
                    {
                        "method": "POST",
                        "path": self.path,
                        "authorization": self.headers.get("Authorization", ""),
                        "function": request.get("function", ""),
                        "project": request.get("payload", {}).get("project", ""),
                    }
                )
                if self.path != "/v1/functions/call":
                    self.send_error(404)
                    return
                function_id = request["function"]
                request_payload = request.get("payload", {})
                if function_id == "packs.bundle.get":
                    version = str(request_payload.get("version") or "1.1.0")
                    result = _pack_bundle(version)
                elif function_id == "packs.project.report":
                    result = {
                        "project_id": 41,
                        "project_slug": "sample",
                        "reported_pack_count": len(request_payload.get("packs", [])),
                    }
                else:
                    result = {
                        "project_id": 41,
                        "project_slug": "sample",
                        "repository_report": None,
                        "packs": [
                            {
                                "slug": "sample-pack",
                                "name": "Sample Pack",
                                "description": "Packaged HTTPS transport fixture.",
                                "latest_version": "1.1.0",
                                "dependencies": [],
                                "documentation": "docs/packs/sample-pack/README.md",
                                "settings_schema": {},
                                "verification": [],
                                "file_count": 1,
                                "status": "available",
                                "installed_version": None,
                            }
                        ],
                    }
                self._send_json(
                    {
                        "success": True,
                        "function": function_id,
                        "version": request["version"],
                        "request_id": request.get("request_id"),
                        "result": result,
                    }
                )

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
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)


__all__ = ["PackApi"]
