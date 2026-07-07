"""Argparse ``--help`` subprocess assertions for the service-client surface.

Every retained CLI adapter exposes a clean ``--help`` flow.
``--help`` MUST exit 0 with ``usage:`` printed to stdout — historical
``add_help=False`` parsers reject ``--help`` as an unknown flag and
return 2 with a misleading "missing required argument" error.

These assertions run the adapters as subprocesses so the bug class is
end-to-end visible (argparse + service-client dispatcher + downstream
handler integration), not just at the in-process call boundary. Each
assertion is one stable invocation; on regression the failing line
points at the exact `--help` surface that broke.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_help(args: list[str]) -> subprocess.CompletedProcess:
    """Run ``python3 -m yoke_core.api.service_client <args>`` as subprocess.

    Returns the CompletedProcess; tests inspect ``returncode`` and
    ``stdout`` (decoded as bytes for the AC's literal-byte assertion).
    Captures stderr too for diagnostic context on failure.
    """
    return subprocess.run(
        [sys.executable, "-m", "yoke_core.api.service_client", *args],
        capture_output=True,
        cwd=str(_REPO_ROOT),
        timeout=30,
    )


def test_path_claim_register_help_exits_zero_with_usage() -> None:
    """AC-28: ``path-claim-register --help`` exits 0 with usage to stdout."""
    proc = _run_help(["path-claim-register", "--help"])
    assert proc.returncode == 0, (
        f"expected exit 0; got {proc.returncode}; "
        f"stderr={proc.stderr.decode(errors='replace')!r}"
    )
    assert b"usage:" in proc.stdout


def test_release_work_claim_help_enumerates_halt_class_reasons() -> None:
    """AC-43: ``release-work-claim --help`` lists canonical halt-class reasons."""
    from yoke_core.api.service_client_work_claim_reason_help import (
        HALT_CLASS_REASONS,
    )
    proc = _run_help(["release-work-claim", "--help"])
    assert proc.returncode == 0, (
        f"expected exit 0; got {proc.returncode}; "
        f"stderr={proc.stderr.decode(errors='replace')!r}"
    )
    body = proc.stdout.decode(errors="replace")
    assert "usage:" in body
    # Every canonical halt-class value must appear in the help text so
    # operators can discover the enum without reading source.
    for reason in HALT_CLASS_REASONS:
        # argparse may line-wrap long reason names; normalize whitespace
        # before substring matching to stay resilient to wrap width.
        normalized = " ".join(body.split())
        assert reason in normalized, (
            f"halt-class reason {reason!r} missing from --help body; "
            f"got: {normalized[:600]!r}"
        )


def test_path_claim_boundary_help_exits_zero_with_usage() -> None:
    """AC-28: ``path-claim-boundary --help`` exits 0 with usage to stdout."""
    proc = _run_help(["path-claim-boundary", "--help"])
    assert proc.returncode == 0, (
        f"expected exit 0; got {proc.returncode}; "
        f"stderr={proc.stderr.decode(errors='replace')!r}"
    )
    assert b"usage:" in proc.stdout


def test_session_end_help_exits_zero_with_usage() -> None:
    """AC-11: ``session-end --help`` exits 0 with usage to stdout."""
    proc = _run_help(["session-end", "--help"])
    assert proc.returncode == 0, (
        f"expected exit 0; got {proc.returncode}; "
        f"stderr={proc.stderr.decode(errors='replace')!r}"
    )
    assert b"usage:" in proc.stdout


def test_claim_release_help_exits_zero_with_usage() -> None:
    """AC-11: ``claim-release --help`` exits 0 with usage to stdout."""
    proc = _run_help(["claim-release", "--help"])
    assert proc.returncode == 0, (
        f"expected exit 0; got {proc.returncode}; "
        f"stderr={proc.stderr.decode(errors='replace')!r}"
    )
    assert b"usage:" in proc.stdout
    # AC-11 synonym pair: both --item and --item-id are listed.
    assert b"--item-id" in proc.stdout
    assert b"--item " in proc.stdout or b"--item " in proc.stdout.replace(
        b"--item-id", b""
    )


def test_backlog_cli_freeze_help_exits_zero_with_usage() -> None:
    """AC-11: ``backlog-cli freeze --help`` exits 0 with usage to stdout."""
    proc = _run_help(["backlog-cli", "freeze", "--help"])
    assert proc.returncode == 0, (
        f"expected exit 0; got {proc.returncode}; "
        f"stderr={proc.stderr.decode(errors='replace')!r}"
    )
    assert b"Usage: backlog-cli freeze" in proc.stdout


# ---------------------------------------------------------------------------
# YOK-1711 AC-6 / AC-7 / AC-8 — universal --help safety net.
# ---------------------------------------------------------------------------


def test_ac6_execute_structured_write_help_exits_zero_with_usage() -> None:
    """AC-6: ``execute-structured-write --help`` exits 0, prints usage."""
    proc = _run_help(["execute-structured-write", "--help"])
    assert proc.returncode == 0, (
        f"expected exit 0; got {proc.returncode}; "
        f"stderr={proc.stderr.decode(errors='replace')!r}"
    )
    assert b"Usage: execute-structured-write" in proc.stdout
    assert b"<item-id>" in proc.stdout


def test_ac6_execute_structured_write_dash_h_exits_zero_with_usage() -> None:
    """AC-6: ``execute-structured-write -h`` matches the long-form behavior."""
    proc = _run_help(["execute-structured-write", "-h"])
    assert proc.returncode == 0
    assert b"Usage: execute-structured-write" in proc.stdout


def test_ac7_flag_first_positional_names_real_shape() -> None:
    """AC-7: ``execute-structured-write --item YOK-N --field spec`` (the
    agent-natural flag-first shape) returns non-zero with an error
    message that names the actual positional shape — never the cryptic
    ``Item ID must be integer, got '--item'`` of the old code path.
    """
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "yoke_core.api.service_client",
            "execute-structured-write",
            "--item",
            "YOK-1711",
            "--field",
            "spec",
        ],
        capture_output=True,
        cwd=str(_REPO_ROOT),
        timeout=30,
    )
    assert proc.returncode != 0, "flag-first positional must fail (non-zero exit)"
    body = proc.stdout.decode(errors="replace")
    assert "<item-id>" in body or "positional" in body, (
        f"error must name the real positional shape; got: {body[:300]!r}"
    )
    # The exact "Item ID must be integer, got '--item'" wording is the
    # cryptic legacy message the fix replaces; assert we no longer see
    # it bare (without the helpful usage block).
    assert "Usage: execute-structured-write" in body or "expects a bare numeric" in body


def test_ac8_every_subcommand_exits_zero_on_help(tmp_path) -> None:
    """AC-8: service_client subcommands and db_router domains exit 0 on
    ``--help`` and create no file artifacts in cwd. The dispatcher's
    universal safety net (`service_client_help.run_with_help_fallback`)
    catches subcommands that crash or return non-zero and replaces
    their noise with a clean fallback usage block.
    """
    import os

    from yoke_core.cli.db_router_dispatch import _DOMAIN_PY_MODULES
    from yoke_core.api.service_client import COMMANDS

    # Subprocess needs runtime/ importable; cwd is the isolated tmp_path
    # so any accidental file artifacts surface immediately.
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")

    failures: list[tuple[str, int, str]] = []
    for cmd in sorted(COMMANDS.keys()):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "yoke_core.api.service_client",
                cmd,
                "--help",
            ],
            capture_output=True,
            cwd=str(tmp_path),
            env=env,
            timeout=30,
        )
        if proc.returncode != 0:
            failures.append((
                f"service_client {cmd}",
                proc.returncode,
                proc.stderr.decode(errors="replace")[:200],
            ))
    for domain in sorted(_DOMAIN_PY_MODULES.keys()):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "yoke_core.cli.db_router",
                domain,
                "--help",
            ],
            capture_output=True,
            cwd=str(tmp_path),
            env=env,
            timeout=30,
        )
        if proc.returncode != 0:
            failures.append((
                f"db_router {domain}",
                proc.returncode,
                proc.stderr.decode(errors="replace")[:200],
            ))

    leftover = sorted(p.name for p in tmp_path.iterdir())
    assert not failures, (
        "--help failed for: "
        + "\n".join(f"  {c} rc={rc} stderr={err!r}" for c, rc, err in failures)
    )
    assert not leftover, f"unexpected file artifacts in cwd: {leftover}"
