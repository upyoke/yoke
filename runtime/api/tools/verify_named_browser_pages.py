"""Controller-local CLI proof that switching named pages preserves form state."""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

FIXTURE = """<!doctype html><input id="name"><p id="status">fresh</p>
<button id="go">Submit</button><p id="result"></p><script>
const nameInput = document.querySelector('#name');
nameInput.addEventListener('input', () => {
  document.querySelector('#status').textContent = 'edited';
});
document.querySelector('#go').addEventListener('click', () => {
  document.querySelector('#result').textContent = nameInput.value;
});
</script>"""


def cli(*args: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "yoke_cli.main", *args],
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            f"named_page_check_failed: yoke {' '.join(args[:3])} exited "
            f"{result.returncode}: {result.stderr}; repair the named browser "
            "runtime problem and rerun this check."
        )
    return result.stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    project = parser.parse_args().project
    help_text = cli("qa", "browser", "step", "--help")
    if "--page NAME" not in help_text or "exploratory" not in help_text:
        raise RuntimeError("named_page_help_missing: restore --page help and rerun.")
    with tempfile.TemporaryDirectory(prefix="named-browser-pages-") as directory:
        Path(directory, "form.html").write_text(FIXTURE)
        handler = functools.partial(
            http.server.SimpleHTTPRequestHandler, directory=directory
        )
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"
        identity = "named-page-proof"
        steps = [
            ("A", {"action": "navigate", "route": "/form.html"}),
            ("A", {"action": "fill_form", "fields": {"#name": "kept-value"}}),
            ("B", {"action": "navigate", "route": "/form.html"}),
            ("B", {"action": "fill_form", "fields": {"#name": "other"}}),
            (
                "A",
                {
                    "action": "assert",
                    "target": "#status",
                    "check": "text_equals",
                    "expected": "edited",
                },
            ),
            ("A", {"action": "click", "target": "#go"}),
            (
                "A",
                {
                    "action": "assert",
                    "target": "#result",
                    "check": "text_equals",
                    "expected": "kept-value",
                },
            ),
        ]
        try:
            for page, step in steps:
                output = cli(
                    "qa",
                    "browser",
                    "step",
                    "--project",
                    project,
                    "--identity",
                    identity,
                    "--page",
                    page,
                    "--base-url",
                    base_url,
                    "--step-json",
                    json.dumps(step),
                )
                print(
                    json.dumps(
                        {"page": page, "step": step, "output": json.loads(output)}
                    ),
                    flush=True,
                )
                response = json.loads(output)
                if not response.get("success") or not response.get("data", {}).get(
                    "success"
                ):
                    raise RuntimeError(
                        "named_page_state_lost: inspect the recorded step JSON, "
                        "repair page selection or retention, and rerun."
                    )
        finally:
            try:
                print(
                    cli(
                        "qa",
                        "browser",
                        "stop",
                        "--project",
                        project,
                        "--identity",
                        identity,
                    ),
                    flush=True,
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(
            f"named_page_proof_failed: {exc}; inspect the step JSON and browser "
            "diagnostic, repair the named problem, and rerun this controller check.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
