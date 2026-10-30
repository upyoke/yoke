"""Release proof for environment-specific install advice and served copy."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

from yoke_cli.config.install_advice import install_command
from yoke_contracts.api_urls import DISTRIBUTION_PROD_URL, DISTRIBUTION_STAGE_URL
from yoke_cli.project_install.managed_git_hooks import managed_git_hook_specs
from yoke_contracts.machine_config.paths import select_read_config
from yoke_core.domain.main_agent_packet import render_install_advisory_block
from unittest.mock import patch


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=("stage", "prod"), required=True)
    args = parser.parse_args()
    origin = (
        DISTRIBUTION_STAGE_URL if args.environment == "stage" else DISTRIBUTION_PROD_URL
    )
    expected = f"curl -fsSL {origin}/install | sh"
    # The registered CLI owns the live read; no API/client bypass is needed.
    reply = subprocess.run(
        ["yoke", "--env", args.environment, "overview", "activation", "get", "--json"],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    envelope = json.loads(reply.stdout)
    if (
        not envelope.get("success")
        or envelope.get("result", {}).get("install_command") != expected
    ):
        raise SystemExit(
            "served_install_authority_mismatch: update the serving release and its "
            "distribution origin, then rerun this case"
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
