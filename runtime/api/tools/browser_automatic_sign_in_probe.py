"""Synthetic background-process proof of automatic authorize and Browser QA.

Only the case's control-plane reads/writes are replaced with in-memory fixtures.
Authorize, local secret files, Chromium, daemon startup and case steps are real.
No real account, GUI, operator prompt or control-plane mutation is involved.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import secrets
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs


def _server(password):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            signed_in = "session=synthetic" in self.headers.get("Cookie", "")
            if self.path == "/me":
                self.send_response(204 if signed_in else 401)
                self.end_headers()
                return
            if self.path == "/logout":
                self.send_response(303)
                self.send_header("Set-Cookie", "session=; Path=/; Max-Age=0")
                self.send_header("Location", "/login")
                self.end_headers()
                return
            body = (
                '<main data-test="authenticated">Synthetic workflow ready</main>'
                if signed_in
                else '<form method="POST" action="/login">'
                '<input name="password" id="password" type="password">'
                "<button>Sign in</button></form>"
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body.encode())

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
            accepted = parse_qs(body).get("password") == [password]
            self.send_response(303)
            if accepted:
                self.send_header(
                    "Set-Cookie", "session=synthetic; Path=/; Max-Age=3600"
                )
            self.send_header("Location", "/private" if accepted else "/login")
            self.end_headers()

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


def _case(project, declarations, origin, records):
    from yoke_contracts.browser_identity import parse_identity_declarations
    from yoke_core.domain import browser_qa

    config = {
        "browser_identity": "buyer",
        "steps": [
            {"action": "navigate", "route": "/private"},
            {"action": "navigate", "route": "/logout"},
            {"action": "sign_in", "site": "shop"},
            {
                "action": "assert",
                "target": "[data-test=authenticated]",
                "check": "visible",
            },
            {"action": "navigate", "route": "/logout"},
            {"action": "assert", "target": "#password", "check": "visible"},
        ],
    }
    context = {
        "standalone_execution_id": "synthetic-background",
        "requirements": [
            {
                "id": 1,
                "qa_kind": "plan_case",
                "method_id": "browser-check",
                "method_config": json.dumps(config),
            }
        ],
    }

    def record(*args, **kwargs):
        records.append(json.dumps([args, kwargs], default=str))
        return 1

    with contextlib.ExitStack() as stack:
        stack.enter_context(
            patch.object(browser_qa, "_fetch_browser_context", return_value=context)
        )
        stack.enter_context(
            patch.object(
                browser_qa,
                "load_project_browser_identities",
                return_value=parse_identity_declarations(declarations),
            )
        )
        for name in (
            "_record_run",
            "_complete_run",
            "_record_artifact",
            "_record_artifact_file",
        ):
            stack.enter_context(patch.object(browser_qa, name, side_effect=record))
        return browser_qa.execute_scenario(project, 1, base_url=origin)


def _probe():
    from yoke_cli.commands.browser_authorize import browser_authorize
    from yoke_cli.config.capability_secrets import store_machine_capability_secret
    from yoke_cli.config import browser_profile
    from yoke_harness import browser_client

    project = "browser-probe"
    password = secrets.token_urlsafe(32)
    server = _server(password)
    origin = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    declarations = {
        "identities": {
            "buyer": {
                "sites": [
                    {
                        "site": "shop",
                        "origin": origin,
                        "probe": {"url": origin + "/me", "signed_in_status": 204},
                        "sign_in": {
                            "mode": "automatic",
                            "url": origin + "/login",
                            "steps": [
                                {"fill": "#password", "secret": "password"},
                                {"click": "button"},
                            ],
                        },
                    }
                ]
            }
        }
    }
    output, records = io.StringIO(), []
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            store_machine_capability_secret(
                project, "browser-control", "sign-in.buyer.shop.password", password
            )
            code = browser_authorize(
                [
                    "--project",
                    project,
                    "--identity",
                    "buyer",
                    "--declarations-json",
                    json.dumps(declarations),
                    "--json",
                ]
            )
            assert code == 0, "authorize_failed"
            receipt = json.loads(output.getvalue().splitlines()[-1])
            assert receipt["ok"] and not receipt["window_opened"], "window_opened"
            # A second fresh profile forces the case's own automatic startup
            # to sign in; it cannot ride the authorize result's cookies.
            browser_profile.remove_profile_dir(project, identity="buyer")
            result = _case(project, declarations, origin, records)
            assert result.verdict == "pass" and result.executed == 1, "case_failed"
            assert (
                password
                not in output.getvalue() + json.dumps(records) + result.to_json()
            ), "secret_exposed"
        return {
            "ok": True,
            "background_child": True,
            "authorize_window_opened": False,
            "case_verdict": result.verdict,
            "executed": result.executed,
            "secret_absent_from_output_and_evidence": True,
            "in_run_sign_in_and_sign_out": True,
            "control_plane": "in-memory fixture; real browser and case steps",
        }
    finally:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            profile = browser_profile.authorized_profile_dir(project, identity="buyer")
            if profile:
                browser_client.daemon_stop(profile_dir=str(profile))
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def main():
    if "--child" in sys.argv:
        try:
            result = _probe()
        except Exception:
            # A browser exception can carry fill call logs; never print it.
            print(
                json.dumps(
                    {
                        "ok": False,
                        "reason": "browser_background_probe_failed",
                        "recovery": "Run the focused automatic sign-in regressions.",
                    }
                )
            )
            return 1
        print(json.dumps(result))
        return 0
    with tempfile.TemporaryDirectory(prefix="browser-background-probe-") as directory:
        env = dict(
            os.environ,
            YOKE_MACHINE_HOME=str(Path(directory) / "machine"),
            DISPLAY="",
            WAYLAND_DISPLAY="",
        )
        result = subprocess.run(
            [sys.executable, "-m", __spec__.name, "--child"],
            env=env,
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=240,
            check=False,
        )
        # The child prints only a closed, credential-free result document.
        payload = json.loads(result.stdout)
        print(json.dumps(payload))
        return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
