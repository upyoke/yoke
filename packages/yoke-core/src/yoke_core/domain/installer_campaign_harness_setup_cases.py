"""Installed-candidate proof of late harness setup, isolated from personal homes."""

import shlex


def harness_setup_cases(command_case):
    return (
        command_case(
            29,
            "harness-installed-after-yoke",
            '"$(uv tool dir)/yoke-cli-releases/current/tools/yoke-cli/bin/python3" -c '
            + shlex.quote(
                "from yoke_core.domain.installer_campaign_harness_setup_cases import run_probe; run_probe()"
            ),
            execution_mode="terminal",
            instructions=(
                "Run the installed candidate against an isolated home and a real Git checkout "
                "with two registered worktrees. Inject only the checkout registry mapping. "
                "Start with no harness home, create Codex's home, then run one relay refresh "
                "without setup or project reinstall. Keep personal sign-in and settings untouched."
            ),
            outcome=(
                "Absent homes stay absent; one relay cycle trusts all three paths, configures "
                "posture and machine hooks, records the fingerprint, and a second pass changes no bytes."
            ),
        ),
    )


def run_probe() -> None:
    """Exercise the real writers and Git inventory without touching a live project."""
    import json
    import os
    import subprocess
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from types import SimpleNamespace
    from unittest.mock import patch

    from yoke_contracts import claude_posture_install
    from yoke_harness import harness_setup_reconcile as setup
    from yoke_harness import session_relay_harness_reconcile as relay

    with TemporaryDirectory(prefix="harness-setup-proof-") as directory:
        root = Path(directory)
        home = root / "home"
        home.mkdir()
        checkout = root / "checkout"
        checkout.mkdir()

        def git(*args):
            subprocess.run(
                ["git", "-C", str(checkout), *args],
                check=True,
                capture_output=True,
                timeout=30,
            )

        git("init")
        hooks = checkout / ".codex/hooks.json"
        hooks.parent.mkdir()
        hooks.write_text(
            json.dumps(
                {
                    "hooks": {
                        "Stop": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "yoke hook evaluate Stop",
                                    }
                                ]
                            }
                        ]
                    }
                }
            )
        )
        git("add", ".codex/hooks.json")
        git(
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "-m",
            "Fixture hooks",
        )
        for name in ("lane-a", "lane-b"):
            git("worktree", "add", "--detach", str(root / name))
        environment = {"HOME": str(home), "CODEX_HOME": str(home / ".codex")}
        with (
            patch.dict(os.environ, environment),
            patch.object(
                setup,
                "configured_projects",
                return_value=[SimpleNamespace(checkout=checkout)],
            ),
            patch.object(
                claude_posture_install, "CLAUDE_APP_CONFIG_PATH", home / "desktop.json"
            ),
        ):
            initial = setup.reconcile_harness_setup()
            if initial.failed or any(home.iterdir()):
                raise RuntimeError(
                    "absent_harness_home_created: repair shared setup before rerunning"
                )
            (home / ".codex").mkdir()
            with (
                patch.object(relay, "refresh_surface_probe_cache", return_value=None),
                patch.object(
                    relay, "state_path", return_value=home / "relay-state.json"
                ),
            ):
                relay.refresh_harness_inventory()
                state = relay.read_reconcile_state()
            result = setup.inspect_harness_setup()
            targets = {
                r.target_path
                for r in result.rows
                if r.harness_id == "codex" and r.facet == "folder_trust"
            }
            if (
                result.failed
                or len(targets) != 3
                or state.get("fingerprint") != ["codex"]
            ):
                raise RuntimeError(
                    f"late_harness_setup_incomplete: inspect setup rows: {result.lines()}"
                )
            before = {p: p.read_bytes() for p in home.rglob("*") if p.is_file()}
            again = setup.reconcile_harness_setup()
            after = {p: p.read_bytes() for p in home.rglob("*") if p.is_file()}
            if before != after or any(
                r.outcome not in ("already_set", "skipped_not_installed")
                for r in again.rows
            ):
                raise RuntimeError(
                    "harness_setup_not_idempotent: inspect writer output before rerunning"
                )
    print(
        "late harness: absent homes preserved; three Git paths ready in one relay cycle; idempotent"
    )
