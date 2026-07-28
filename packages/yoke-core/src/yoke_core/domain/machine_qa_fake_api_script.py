"""Remote fake-Yoke API program uploaded by Machine QA fixtures."""

FAKE_API_SERVER_SCRIPT = r"""from __future__ import annotations

import hashlib
import http.server
import json
import socketserver
import sys
import time

profile_path, raw_port, identity = sys.argv[1:4]
profile = json.loads(open(profile_path, encoding="utf-8").read())
port = int(raw_port)
function_rows = profile.get("function_rows") or []
function_errors = profile.get("function_errors") or {}
function_delays = profile.get("function_delays") or {}
project_template = profile.get("project") or {
    "id": 91,
    "slug": "recipe-meta",
    "name": "Recipe Meta",
    "github_repo": "recipe/meta",
    "default_branch": "main",
    "public_item_prefix": "REC",
}


def project_from_request(request):
    project = dict(project_template)
    for key in (
        "slug",
        "name",
        "github_repo",
        "default_branch",
        "public_item_prefix",
    ):
        if request.get(key):
            project[key] = request[key]
    project.setdefault("id", 91)
    return project


def install_bundle(project):
    strategy_body = "# Mission\n\nOperate this project through Yoke.\n"
    digest = hashlib.sha256(strategy_body.encode()).hexdigest()
    strategy = (
        "<!-- YOKE:STRATEGY-DOC slug=MISSION "
        "updated_at=2026-06-16T00:00:00Z content_sha256="
        + digest
        + " -->\n"
        + strategy_body
    )
    bundle = {
        "bundle_schema": 1,
        "yoke_version": "9.9.9",
        "project_id": int(project.get("id") or 91),
        "project_slug": project.get("slug") or "recipe-meta",
        "files": [
            {
                "path": ".codex/skills/yoke/onboard/SKILL.md",
                "content": "# onboard\n",
            }
        ],
        "project_contract_files": [
            {
                "path": ".yoke/lint-config",
                "content": "lint_main_commit=deny\n",
                "install_policy": "seed_if_missing",
                "category": "project_policy",
            }
        ],
        "strategy_files": [
            {
                "path": ".yoke/strategy/MISSION.md",
                "content": strategy,
                "install_policy": "db_render",
            }
        ],
        "hooks": {},
    }
    if profile.get("install_bundle_board_art_conflict"):
        bundle["project_contract_files"].append(
            {
                "path": ".yoke/board-art/sentinel",
                "content": "conflict\n",
                "install_policy": "seed_if_missing",
                "category": "project_policy",
            }
        )
    return bundle


class Handler(http.server.BaseHTTPRequestHandler):
    def send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/__fixture_identity__":
            self.send_json(200, {"identity": identity})
            return
        if (
            self.path.startswith("/v1/projects/")
            and self.path.endswith("/install-bundle")
        ):
            self.send_json(200, install_bundle(project_template))
            return
        self.send_json(200, profile)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        try:
            request = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            request = {}
        function = str(request.get("function") or "")
        if function in function_delays:
            time.sleep(float(function_delays[function]))
        response = {
            "success": True,
            "function": function,
            "version": request.get("version") or "v1",
            "request_id": request.get("request_id"),
            "result": {},
            "warnings": [],
            "event_ids": [],
        }
        if function in function_errors:
            error = function_errors[function]
            response["success"] = False
            response["error"] = {
                "code": error["code"],
                "message": error["message"],
            }
            self.send_json(200, response)
            return
        payload = request.get("payload") or {}
        if function == "projects.list":
            response["result"] = {"rows": function_rows}
        elif function == "projects.get":
            response["result"] = {
                "row": project_template,
                "project": project_template,
            }
        elif function == "projects.resolve_by_github_repo":
            response["result"] = {"row": project_template}
        elif function == "projects.create":
            response["result"] = {
                "project": project_from_request(payload),
            }
        elif function == "projects.capability_secret.set":
            response["result"] = {
                "project": payload.get("project"),
                "cap_type": payload.get("cap_type"),
                "key": payload.get("key"),
                "source": payload.get("source") or "literal",
                "stored": True,
            }
        elif function == "onboard.checklist.run":
            response["result"] = {
                "schema_version": 1,
                "operation": function,
                "run_id": payload.get("run_id") or "run-handoff",
                "resumed": False,
                "branch": payload.get("branch"),
                "project_id": payload.get("project_id"),
                "checkout_path": payload.get("checkout_path"),
                "github_repo": payload.get("github_repo"),
                "status": "open",
                "rows": [],
                "summary": {"status": "open"},
            }
        elif function == "project.snapshot.sync":
            response["result"] = {
                "snapshots": [
                    {
                        "status": "created",
                        "ref": "HEAD",
                        "commit_sha": "abc123",
                        "snapshot_id": 99,
                    }
                ],
                "warnings": [],
            }
        elif function == "board.data.get":
            response["result"] = {}
        else:
            response["success"] = False
            response["error"] = {
                "code": "unsupported_fake_function",
                "message": function,
            }
        self.send_json(200, response)

    def log_message(self, *_args):
        return


class ReuseServer(socketserver.TCPServer):
    allow_reuse_address = True


with ReuseServer(("127.0.0.1", port), Handler) as server:
    server.serve_forever()
"""


__all__ = ["FAKE_API_SERVER_SCRIPT"]
