"""Product-boundary coverage for strategy/event/Ouroboros adapters."""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator

from runtime.api.cli.test_yoke_product_boundary_fault_injection import (
    _assert_clean_client_boundary,
    _run_product_cli,
)


@contextmanager
def _fake_function_server() -> Iterator[tuple[str, list[dict]]]:
    requests: list[dict] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - http.server API
            length = int(self.headers.get("Content-Length") or "0")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            requests.append(payload)
            result = _result_for(payload["function"])
            body = json.dumps(
                {
                    "success": True,
                    "function": payload["function"],
                    "version": payload.get("version", "v1"),
                    "request_id": payload.get("request_id"),
                    "result": result,
                    "warnings": [],
                    "error": None,
                    "event_ids": [],
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _result_for(function_id: str) -> dict:
    if function_id == "events.emit":
        return {"emitted": True, "event_id": "evt-test", "reason": ""}
    if function_id == "strategy.master_plan_check.run":
        return {
            "report": {"contradictions": [], "advisories": []},
            "markdown_report": "No contradictions found.\n",
            "contradiction_count": 0,
        }
    return {"ok": True}


def _https_config(tmp_path: Path, api_url: str) -> dict:
    token_path = tmp_path / "token.txt"
    token_path.write_text("tok\n", encoding="utf-8")
    return {
        "schema_version": 1,
        "active_env": "test",
        "connections": {
            "test": {
                "transport": "https",
                "api_url": api_url,
                "credential_source": {
                    "kind": "token_file",
                    "path": str(token_path),
                },
            },
        },
    }


def test_strategy_event_ouroboros_help_stays_product_safe(
    tmp_path: Path,
) -> None:
    commands = (
        (("events", "emit", "--help"), "usage: yoke events emit"),
        (
            ("strategy", "master-plan-check", "--help"),
            "usage: yoke strategy master-plan-check",
        ),
        (
            ("ouroboros", "entry", "insert", "--help"),
            "usage: yoke ouroboros entry insert",
        ),
    )

    for args, expected in commands:
        run = _run_product_cli(tmp_path / "-".join(args), args)
        assert run.returncode == 0
        assert expected in run.stdout
        assert run.stderr == ""
        _assert_clean_client_boundary(run)


def test_events_emit_invocation_stays_product_safe(tmp_path: Path) -> None:
    with _fake_function_server() as (api_url, requests):
        run = _run_product_cli(
            tmp_path,
            [
                "events",
                "emit",
                "--name",
                "FeedCompleted",
                "--kind",
                "lifecycle",
                "--type",
                "feed",
                "--source-type",
                "skill",
                "--severity",
                "STATUS",
                "--project",
                "yoke",
                "--context",
                '{"mode":"direct"}',
                "--error-context",
                '{"error_category":"validation"}',
                "--json",
            ],
            config_payload=_https_config(tmp_path, api_url),
        )

    assert run.returncode == 0
    _assert_clean_client_boundary(run)
    assert len(requests) == 1
    request = requests[0]
    assert request["function"] == "events.emit"
    assert request["payload"]["context"] == {
        "detail": {"mode": "direct"},
        "error": {"error_category": "validation"},
    }
    assert json.loads(run.stdout)["success"] is True


def test_master_plan_check_invocation_stays_product_safe(
    tmp_path: Path,
) -> None:
    plan_path = tmp_path / "MASTER-PLAN.md"
    plan_text = "## 5. Backlog By Generation\n\n#### Remaining frontier\n"
    plan_path.write_text(plan_text, encoding="utf-8")

    with _fake_function_server() as (api_url, requests):
        run = _run_product_cli(
            tmp_path,
            [
                "strategy",
                "master-plan-check",
                "--plan-path",
                str(plan_path),
                "--json",
            ],
            config_payload=_https_config(tmp_path, api_url),
        )

    assert run.returncode == 0
    _assert_clean_client_boundary(run)
    assert len(requests) == 1
    request = requests[0]
    assert request["function"] == "strategy.master_plan_check.run"
    assert request["payload"] == {"markdown": plan_text}
    assert json.loads(run.stdout)["success"] is True
