# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from concurrent.futures import ThreadPoolExecutor

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pathlib import Path

import json

import os

import shutil

import threading

import time

import pytest

from yoke_contracts.browser_qa_contract import DEFAULT_BROWSER_VIEWPORT

from yoke_contracts.browser_step_schema import load_schema

from yoke_contracts.playwright_cache import (
    YOKE_BROWSER_CACHE_PROJECT,
    resolve_playwright_cache,
)

from yoke_core.domain import browser_client as core_client

from yoke_harness import browser_client, browser_runtime, browser_runtime_home

from yoke_harness.browser_daemon_profile import profile_scope


class ProbeHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        name = self.path.strip("/") or "empty"
        body = f"<html><body>{name}; cookie={self.headers.get('Cookie', 'none')}</body></html>".encode()
        self.send_response(200)
        if name in {"alpha", "beta"}:
            self.send_header("Set-Cookie", f"profile={name}; Path=/")
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture()
def daemon_runtime(tmp_path, monkeypatch):
    installed = Path(
        os.environ.get("YOKE_BROWSER_TEST_RUNTIME")
        or Path.home() / ".yoke" / browser_runtime_home.RUNTIME_DIR_NAME
    )
    if (
        not shutil.which("node")
        or not (installed / "node_modules" / "playwright").is_dir()
    ):
        if os.environ.get("DEPLOYMENT_RUN_ID"):
            pytest.fail(
                "install the host Playwright runtime before deployed capture QA"
            )
        pytest.skip("machine has no materialized Playwright browser runtime")
    runtime = tmp_path / "runtime"
    shutil.copytree(Path(browser_runtime.__file__).parent / "src", runtime / "src")
    (runtime / "src" / "step-schema.json").write_text(json.dumps(load_schema()))
    (runtime / "node_modules").symlink_to(
        installed / "node_modules", target_is_directory=True
    )
    monkeypatch.setattr(browser_client, "_browser_dir", lambda: runtime)
    monkeypatch.setattr(core_client, "_browser_dir", lambda: runtime)
    env = dict(os.environ)
    configured_cache = os.environ.get("YOKE_BROWSER_TEST_CACHE")
    cache = (
        Path(configured_cache)
        if configured_cache
        else resolve_playwright_cache(YOKE_BROWSER_CACHE_PROJECT, None)
    )
    host_cache = Path.home() / ".yoke" / "playwright-cache" / YOKE_BROWSER_CACHE_PROJECT
    if not cache and host_cache.is_dir():
        cache = host_cache
    if cache:
        env["PLAYWRIGHT_BROWSERS_PATH"] = str(cache)
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(cache))
    monkeypatch.setattr(
        "yoke_harness.browser_client.ensure_browser_runtime",
        lambda *args, **kwargs: env,
    )
    return runtime
