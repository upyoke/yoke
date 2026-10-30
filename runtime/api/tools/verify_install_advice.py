"""Release proof for environment-specific install advice and served copy."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from yoke_cli.config.install_advice import install_command
from yoke_contracts.api_urls import DISTRIBUTION_PROD_URL, DISTRIBUTION_STAGE_URL
from yoke_cli.project_install.managed_git_hooks import managed_git_hook_specs
from yoke_contracts.machine_config.paths import select_read_config
from yoke_core.domain.main_agent_packet import render_install_advisory_block
from unittest.mock import patch


def read_served_command(environment: str) -> str:
    """Keep a failed registered read's diagnosis in the case capture."""
    command = ["yoke", "--env", environment, "overview", "activation", "get", "--json"]
    try:
        reply = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(
            f"install_advice_read_unavailable: {environment} activation read: {exc}; "
            "restore the CLI/connection and rerun this case"
        ) from None
    try:
        envelope = json.loads(reply.stdout)
    except ValueError:
        envelope = None
    if (
        not isinstance(envelope, dict)
        or reply.returncode
        or not envelope.get("success")
    ):
        error = envelope.get("error") if isinstance(envelope, dict) else None
        print(
            f"install_advice_read_failed: {environment} activation read exited "
            f"{reply.returncode}; error={json.dumps(error, ensure_ascii=False)}",
            file=sys.stderr,
        )
        if reply.stderr.strip():
            print(reply.stderr.strip(), file=sys.stderr)
        raise SystemExit(
            "Repair the reported activation error and rerun this case; "
            "no install authority was verified"
        )
    result = envelope.get("result")
    return result.get("install_command", "") if isinstance(result, dict) else ""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=("stage", "prod"), required=True)
    args = parser.parse_args()
    origin = (
        DISTRIBUTION_STAGE_URL if args.environment == "stage" else DISTRIBUTION_PROD_URL
    )
    expected = f"curl -fsSL {origin}/install | sh"
    observed = read_served_command(args.environment)
    if observed != expected:
        raise SystemExit(
            f"served_install_authority_mismatch: expected {expected!r}, observed {observed!r}; "
            "update the serving release and its distribution origin, then rerun this case"
        )
    with tempfile.TemporaryDirectory(prefix="yoke-install-advice-") as scratch:
        config = Path(scratch) / "config.json"
        config.write_text(
            json.dumps(
                {
                    "settings": {
                        "distribution": {
                            "origin": origin,
                            "channel": "stable",
                        }
                    }
                }
            )
        )
        with select_read_config(config), patch.dict(os.environ, {}, clear=False):
            os.environ.pop("YOKE_INSTALL_BASE_URL", None)
            assert install_command() == expected
            with patch("shutil.which", return_value=None):
                assert expected in render_install_advisory_block()
            for spec in managed_git_hook_specs():
                assert expected in spec["content"]
    print(
        f"PASS: {args.environment} served onboarding and machine repair advice use {origin}"
    )


if __name__ == "__main__":
    main()
