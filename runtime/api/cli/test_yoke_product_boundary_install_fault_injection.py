"""Fault-injection proof for project install under product-client authority."""

from __future__ import annotations

import http.server
import json
import threading
from pathlib import Path
from typing import Any, Mapping

from runtime.api.cli.test_yoke_product_boundary_fault_injection import (
    _assert_clean_client_boundary,
    _run_product_cli,
)


PROJECT_ID = 7
PRODUCT_TOKEN = "product-token"


class _BundleServer:
    def __init__(self, bundle: Mapping[str, object]) -> None:
        self.bundle = bundle
        self.requests: list[tuple[str, str]] = []
        self.url = ""
        self._server: http.server.ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "_BundleServer":
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                owner.requests.append((
                    self.path,
                    self.headers.get("Authorization", ""),
                ))
                if self.path != f"/v1/projects/{PROJECT_ID}/install-bundle":
                    self.send_error(404)
                    return
                body = json.dumps(owner.bundle).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)


def test_project_install_https_external_repo_stays_product_client_only(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "external-project"
    checkout.mkdir()
    (checkout / ".git" / "hooks").mkdir(parents=True)
    (checkout / "README.md").write_text("# external\n", encoding="utf-8")
    token_path = tmp_path / "api.token"
    token_path.write_text(PRODUCT_TOKEN + "\n", encoding="utf-8")

    with _BundleServer(_bundle()) as server:
        install = _run_product_cli(
            tmp_path,
            [
                "project",
                "install",
                str(checkout),
                "--project-id",
                str(PROJECT_ID),
            ],
            config_payload=_https_only_config(server.url, token_path),
            client_cwd=checkout,
        )

    assert install.returncode == 0
    payload = json.loads(install.stdout)
    assert payload["operation"] == "install"
    assert payload["mode"] == "copy"
    assert payload["source"] == server.url
    assert payload["machine_config_newly_registered"] is True
    assert server.requests == [
        (
            f"/v1/projects/{PROJECT_ID}/install-bundle",
            f"Bearer {PRODUCT_TOKEN}",
        )
    ]
    assert "delivery strategy = copy (external project repo)" in install.stderr
    _assert_clean_client_boundary(install)

    _assert_installed_project_layer(checkout)
    yoke_home = tmp_path / "home" / ".yoke"
    assert not (yoke_home / "browser-runtime").exists()
    _assert_https_only_machine_config(
        yoke_home / "config.json",
        checkout=checkout,
    )

    status = _run_product_cli(
        tmp_path,
        ["status", "--json"],
        client_cwd=checkout,
    )

    assert status.returncode == 0
    report = json.loads(status.stdout)
    assert report["ok"] is True
    assert report["repo_root"] == str(checkout)
    assert report["connection"]["transport"] == "https"
    assert report["connection"]["client_authority"] == "api"
    assert report["connection"]["credential_source"]["present"] is True
    assert report["project"]["project_id"] == PROJECT_ID
    assert report["db"] == {"relevant": False, "ok": None, "action": ""}
    # status probes /v1/health live on https connections; the stub bundle
    # server is already shut down here, so the unreachable warning is the
    # correct report — and the only acceptable issue.
    assert _issue_codes(report) == {"server_unreachable"}
    assert status.stderr == ""
    _assert_clean_client_boundary(status)


def _bundle() -> dict[str, Any]:
    hook = {
        "matcher": "Bash",
        "hooks": [
            {
                "type": "command",
                "command": "/bin/zsh -lc 'yoke hook evaluate PreToolUse'",
            },
        ],
    }
    return {
        "bundle_schema": 1,
        "yoke_version": "9.9.9",
        "project_id": PROJECT_ID,
        "project_slug": "external-demo",
        "files": [
            {
                "path": ".codex/skills/yoke/onboard-project/SKILL.md",
                "content": "# onboard-project\n",
            },
        ],
        "project_contract_files": [
            {
                "path": ".yoke/file-line-exceptions",
                "content": "# exceptions\n",
                "install_policy": "seed_if_missing",
                "category": "project_policy",
            },
        ],
        "hooks": {
            "claude_settings_hooks": {"PreToolUse": [hook]},
            "codex_hooks": {"PreToolUse": [hook]},
        },
    }


def _https_only_config(api_url: str, token_path: Path) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "active_env": "product",
        "connections": {
            "product": {
                "transport": "https",
                "api_url": api_url,
                "credential_source": {
                    "kind": "token_file",
                    "path": str(token_path),
                },
            },
        },
        "settings": {},
    }


def _assert_installed_project_layer(checkout: Path) -> None:
    installed = {
        path.relative_to(checkout).as_posix()
        for path in checkout.rglob("*")
        if path.is_file()
    }
    assert {
        ".codex/skills/yoke/onboard-project/SKILL.md",
        ".claude/settings.json",
        ".codex/hooks.json",
        ".git/hooks/pre-commit",
        ".git/hooks/post-commit",
        ".yoke/install-manifest.json",
        ".yoke/file-line-exceptions",
    } <= installed
    # The engine reaches machines through the wheel channel, never as source
    # trees copied into a managed project checkout.
    for forbidden_rel in (
        "runtime",
        "packages/yoke-core",
        ".yoke/capabilities",
        ".yoke/secrets",
        ".yoke/qa-artifacts",
        ".yoke/scratch",
        ".yoke/sessions",
        ".yoke/browser-runtime",
    ):
        assert not (checkout / forbidden_rel).exists()


def _assert_https_only_machine_config(config_path: Path, *, checkout: Path) -> None:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assert config["active_env"] == "product"
    assert list(config["connections"]) == ["product"]
    assert config["connections"]["product"]["transport"] == "https"
    assert "postgres" not in config["connections"]["product"]
    assert "github" not in config
    assert config["projects"] == [
        {"checkout": str(checkout.resolve()), "project_id": PROJECT_ID,
         "env": "product"},
    ]


def _issue_codes(report: Mapping[str, object]) -> set[str]:
    return {
        str(issue["code"])
        for issue in report.get("issues", [])
        if isinstance(issue, Mapping) and "code" in issue
    }
