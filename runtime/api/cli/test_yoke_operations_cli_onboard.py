from __future__ import annotations

import io
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from yoke_cli import main as yoke_operations_cli

# The wizard module imports textual lazily; the wizard-driving tests need it.
textual = pytest.importorskip("textual")


def test_onboard_help_exits_cleanly(capsys) -> None:
    rc = yoke_operations_cli.main(["onboard", "--help"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "yoke onboard" in out
    assert "[--config PATH]" in out


def test_onboard_dry_run_prints_write_plan_without_mutation(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    config = tmp_path / "machine" / "config.json"
    token = tmp_path / "token"
    token.write_text("actor-token\n", encoding="utf-8")

    rc = yoke_operations_cli.main([
        "onboard",
        "--non-interactive",
        "--advanced",
        "--config", str(config),
        "--env", "prod",
        "--api-url", "https://api.example.test",
        "--token-file", str(token),
        "--json",
    ])

    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["applied"] is False
    assert payload["mode"] == "advanced"
    assert payload["config_path"] == str(config)
    assert payload["plan"]["active_env"] == "prod"
    assert payload["plan"]["token_source"] == {
        "kind": "token_file", "path": str(token),
    }
    assert payload["plan"]["connection"]["credential_source"]["path"].endswith(
        "secrets/prod.token"
    )
    assert "actor-token" not in out
    assert payload["plan"]["steps"][0]["action"] == "create-or-validate-dir"
    assert "yoke project install" in payload["next_steps"][1]
    assert not config.exists()


def test_onboard_non_interactive_defaults_config_path(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    token = tmp_path / "token"
    token.write_text("actor-token\n", encoding="utf-8")

    rc = yoke_operations_cli.main([
        "onboard",
        "--non-interactive",
        "--quick",
        "--env", "stage",
        "--api-url", "https://api.example.test",
        "--token-file", str(token),
        "--json",
    ])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["applied"] is False
    assert payload["config_path"] == str(home / "config.json")
    assert not (home / "config.json").exists()


def test_onboard_yes_writes_machine_config_after_identity_check(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    config = tmp_path / "home" / "config.json"
    with _registry_server(expected_token="actor-token") as api_url:
        rc = yoke_operations_cli.main([
            "onboard",
            "actor-token",
            "--non-interactive",
            "--quick",
            "--config", str(config),
            "--env", "prod",
            "--api-url", api_url,
            "--yes",
            "--json",
        ])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["applied"] is True
    assert payload["identity"]["status"] == "verified"
    written = json.loads(config.read_text(encoding="utf-8"))
    assert written["active_env"] == "prod"
    stored = tmp_path / "home" / "secrets" / "prod.token"
    assert written["connections"]["prod"] == {
        "transport": "https",
        "api_url": api_url,
        "credential_source": {"kind": "token_file", "path": str(stored)},
    }
    assert stored.read_text(encoding="utf-8") == "actor-token\n"
    assert "actor-token" not in json.dumps(written)
    assert (tmp_path / "home" / "tmp").is_dir()
    assert (tmp_path / "home" / "cache").is_dir()


def test_onboard_yes_accepts_versioned_api_base(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    config = tmp_path / "home" / "config.json"
    with _registry_server(expected_token="actor-token") as api_url:
        versioned_api_url = api_url + "/v1"
        rc = yoke_operations_cli.main([
            "onboard",
            "actor-token",
            "--non-interactive",
            "--quick",
            "--config", str(config),
            "--env", "stage",
            "--api-url", versioned_api_url,
            "--yes",
            "--json",
        ])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["identity"]["url"].endswith("/v1/functions/registry")
    written = json.loads(config.read_text(encoding="utf-8"))
    assert written["connections"]["stage"]["api_url"] == versioned_api_url


def test_onboard_yes_refuses_to_replace_existing_token(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    saved = home / "secrets" / "prod.token"
    saved.parent.mkdir(parents=True)
    saved.write_text("yoke_v1_existing\n", encoding="utf-8")

    rc = yoke_operations_cli.main([
        "onboard",
        "yoke_v1_new",
        "--non-interactive",
        "--quick",
        "--config", str(home / "config.json"),
        "--env", "prod",
        "--api-url", "https://api.example.test",
        "--yes",
        "--json",
    ])

    assert rc == 1
    err = capsys.readouterr().err
    assert "different Yoke API token for prod" in err
    assert "yoke_v1_existing" not in err
    assert "yoke_v1_new" not in err
    assert saved.read_text(encoding="utf-8") == "yoke_v1_existing\n"
    assert not (home / "config.json").exists()


def test_onboard_missing_required_flags_exits_nonzero(capsys) -> None:
    rc = yoke_operations_cli.main(["onboard", "--non-interactive"])

    assert rc == 2
    assert "--api-url" in capsys.readouterr().err


def test_onboard_json_missing_flags_does_not_launch_wizard(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    stdout = _TTYOutput()
    stdin = _TTYInput("")
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)

    rc = yoke_operations_cli.main(["onboard", "--json"])

    assert rc == 2
    assert stdout.getvalue() == ""
    assert "--api-url" in capsys.readouterr().err


def test_onboard_non_tty_does_not_launch_wizard(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    """A non-TTY interactive request must not start Textual; it errors out."""
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    monkeypatch.setattr(sys, "stdout", io.StringIO())

    rc = yoke_operations_cli.main(["onboard"])

    assert rc == 2
    assert "--api-url" in capsys.readouterr().err


class _RegistryServer:
    def __init__(self, *, expected_token: str) -> None:
        self.expected_token = expected_token
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def __enter__(self) -> str:
        expected = self.expected_token

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                auth = self.headers.get("Authorization")
                if self.path != "/v1/functions/registry":
                    self.send_response(404)
                    self.end_headers()
                    return
                if auth != f"Bearer {expected}":
                    self.send_response(403)
                    self.end_headers()
                    return
                body = json.dumps([{"function_id": "status.run"}]).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *args) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True,
        )
        self.thread.start()
        host, port = self.server.server_address
        return f"http://{host}:{port}"

    def __exit__(self, *_exc) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=2)


def _registry_server(*, expected_token: str) -> _RegistryServer:
    return _RegistryServer(expected_token=expected_token)


class _TTYInput(io.StringIO):
    def isatty(self) -> bool:
        return True


class _TTYOutput(io.StringIO):
    def isatty(self) -> bool:
        return True
