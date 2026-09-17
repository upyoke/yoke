"""Materialize this checkout's browser QA runtime onto the machine.

The runtime is copied to ``~/.yoke/browser-runtime`` and the copy is keyed
by a hash of the packaged source, so a lane that changes the step runner
has to hand its version over before a case can execute against it. Run
through ``yoke dev run --`` so the packaged source resolved is the lane's,
not the installed build's.
"""

from __future__ import annotations

from yoke_harness import browser_runtime_home


def main() -> None:
    before = browser_runtime_home.runtime_dir() / browser_runtime_home.HASH_MARKER_NAME
    previous = before.read_text().strip() if before.exists() else "(none)"
    destination = browser_runtime_home.ensure_materialized()
    current = (destination / browser_runtime_home.HASH_MARKER_NAME).read_text().strip()
    print(f"runtime: {destination}")
    print(f"was: {previous}")
    print(f"now: {current}")
    print("changed" if previous != current else "unchanged")


if __name__ == "__main__":
    main()
