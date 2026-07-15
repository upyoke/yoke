"""Public-installer cold-start acceptance preparation.

Generates the per-cell probe scripts that prove the public installer's
``uv tool install`` flow on fresh Linux hosts. Each cell exercises the bare
``curl .../install | sh`` path against Yoke's package index, smokes the
product surface, and audits the product boundary. The browser runtime is
proven on FIRST USE (a separate ``yoke qa browser setup`` cell), not at
install time. The secret-marker scan, AWS identity preflight, and fresh-install
status allowlist are shared with ``installer_cold_start_proof_core``; the
argparse driver lives in ``installer_cold_start_proof_cli``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from yoke_contracts.api_urls import DISTRIBUTION_PROD_URL, DISTRIBUTION_STAGE_URL

from yoke_core.domain import json_helper
from yoke_core.tools.installer_cold_start_proof_core import (
    DEFAULT_AWS_PROJECT,
    DEFAULT_REGION,
    FRESH_STATUS_ERROR_CODES,
    SECRET_MARKERS,
    CommandResult,
    CommandRunner,
    aws_identity_preflight,
    scan_log_file,
    scan_secret_markers,
)

__all__ = [
    "DEFAULT_AWS_PROJECT",
    "DEFAULT_REGION",
    "FRESH_STATUS_ERROR_CODES",
    "SECRET_MARKERS",
    "CommandResult",
    "CommandRunner",
    "LinuxProofCell",
    "aws_identity_preflight",
    "build_parser",
    "first_use_browser_script",
    "linux_proof_cells",
    "main",
    "prepare_evidence_dir",
    "render_linux_probe_script",
    "scan_log_file",
    "scan_secret_markers",
]


# The python-tag families are informational matrix dimensions: uv provisions a
# managed interpreter, so the installer no longer selects a per-target wheelhouse
# by tag. The list documents which managed-Python versions each cell covers.
PYTHON_TAGS: tuple[str, ...] = ("cp310", "cp311", "cp312", "cp313")
DISTROS: tuple[str, ...] = ("amazon-linux-2023", "ubuntu-24.04")
AWS_ARCHES: tuple[str, ...] = ("x86_64", "aarch64")


@dataclass(frozen=True)
class _Endpoint:
    name: str
    base_url: str
    channel: str


ENDPOINTS: tuple[_Endpoint, ...] = (
    _Endpoint("prod", DISTRIBUTION_PROD_URL, "stable"),
    _Endpoint("stage", DISTRIBUTION_STAGE_URL, "latest"),
)


@dataclass(frozen=True)
class LinuxProofCell:
    label: str
    endpoint: str
    base_url: str
    channel: str
    distro: str
    aws_arch: str
    targets: tuple[str, ...]


def linux_proof_cells() -> tuple[LinuxProofCell, ...]:
    cells: list[LinuxProofCell] = []
    for endpoint in ENDPOINTS:
        for distro in DISTROS:
            for arch in AWS_ARCHES:
                cells.append(
                    LinuxProofCell(
                        label=f"{endpoint.name}-{distro}-{arch}",
                        endpoint=endpoint.name,
                        base_url=endpoint.base_url,
                        channel=endpoint.channel,
                        distro=distro,
                        aws_arch=arch,
                        targets=PYTHON_TAGS,
                    )
                )
    return tuple(cells)


def render_linux_probe_script(cell: LinuxProofCell) -> str:
    covered = " ".join(cell.targets)
    fresh_codes = " ".join(FRESH_STATUS_ERROR_CODES)
    return f"""#!/bin/sh
set -eu

LABEL={_sh_single_quote(cell.label)}
ENDPOINT={_sh_single_quote(cell.endpoint)}
INSTALL_BASE_URL={_sh_single_quote(cell.base_url)}
CHANNEL={_sh_single_quote(cell.channel)}
DISTRO={_sh_single_quote(cell.distro)}
AWS_ARCH={_sh_single_quote(cell.aws_arch)}
COVERED_PYTHON={_sh_single_quote(covered)}
# Issue codes a fresh, not-yet-onboarded host reports at error severity. They
# are expected here and must not fail the probe (mirrors install.py's
# FRESH_STATUS_ERROR_CODES / _unexpected_status_error_codes).
FRESH_STATUS_CODES={_sh_single_quote(fresh_codes)}
USER_HOME="${{HOME:-}}"

export YOKE_INSTALL_YES=1
export YOKE_NO_ONBOARD=1

echo "YOKE_E2E_BEGIN $LABEL"
echo "Endpoint: $ENDPOINT"
echo "Distro: $DISTRO"
echo "AWS arch: $AWS_ARCH"
echo "Managed Python coverage: $COVERED_PYTHON"

# The installer ensures uv (Astral installer under --yes), then runs a single
# `uv tool install yoke-cli` with the lockstep product packages (`--with`)
# from the Yoke index. The installer's own product-boundary audit already
# classifies first-run status codes and hard-fails on a broken install.
curl -fsSL "$INSTALL_BASE_URL/install" -o /tmp/yoke-install
chmod +x /tmp/yoke-install
YOKE_INSTALL_BASE_URL="$INSTALL_BASE_URL" YOKE_CHANNEL="$CHANNEL" \\
  sh /tmp/yoke-install --yes

# Non-login SSH commands do not always reread the startup file that the
# installer repaired. Resolve the installed launcher once, then smoke the same
# `yoke ...` surface a fresh login shell would see.
YOKE_BIN=""
if [ -n "${{XDG_BIN_HOME:-}}" ] && [ -x "${{XDG_BIN_HOME}}/yoke" ]; then
  YOKE_BIN="${{XDG_BIN_HOME}}/yoke"
elif [ -n "$USER_HOME" ] && [ -x "$USER_HOME/.local/bin/yoke" ]; then
  YOKE_BIN="$USER_HOME/.local/bin/yoke"
elif [ -x /root/.local/bin/yoke ]; then
  YOKE_BIN=/root/.local/bin/yoke
elif command -v yoke >/dev/null 2>&1; then
  YOKE_BIN="$(command -v yoke)"
else
  echo "yoke command not found after install" >&2
  echo "PATH=$PATH" >&2
  exit 1
fi
YOKE_DIR="$(dirname "$YOKE_BIN")"
case ":$PATH:" in
  *":$YOKE_DIR:"*) ;;
  *) export PATH="$YOKE_DIR:$PATH" ;;
esac

# Smoke the product surface. Browser setup is NOT part of install; it is proven
# on first use by the companion browser cell.
yoke --version
yoke --help >/tmp/yoke-help.txt

# Re-smoke `yoke status --json`. On a fresh, un-onboarded host it exits
# non-zero BY DESIGN (first-run config_missing etc.), so capture it with
# `|| true` rather than letting `set -e` abort a successful install. Still
# assert it produced valid status JSON and reject any error-severity issue
# whose code is outside the first-run allowlist (a genuinely broken install).
yoke status --json >/tmp/yoke-status.json 2>/tmp/yoke-status.err || true
if [ ! -s /tmp/yoke-status.json ]; then
  echo "yoke status --json produced no output after install" >&2
  exit 1
fi
if ! grep -q '"issues"' /tmp/yoke-status.json; then
  echo "yoke status --json did not return a status object" >&2
  exit 1
fi
UNEXPECTED_STATUS_CODES=$(
  awk -v ALLOWED="$FRESH_STATUS_CODES" '
    BEGIN {{ RS="}}"; n=split(ALLOWED, a, " "); for (i=1; i<=n; i++) allow[a[i]]=1 }}
    {{
      seg=$0
      gsub(/[ \\t\\r\\n]/, "", seg)
      if (seg ~ /"severity":"error"/) {{
        if (match(seg, /"code":"[^"]*"/))
          {{ code=substr(seg, RSTART+8, RLENGTH-9); if (!(code in allow)) print code }}
        else print "missing_code"
      }}
    }}
  ' /tmp/yoke-status.json
)
if [ -n "$UNEXPECTED_STATUS_CODES" ]; then
  echo "yoke status reported unexpected errors on a fresh install:" >&2
  echo "$UNEXPECTED_STATUS_CODES" >&2
  exit 1
fi

# Product-boundary audit: a product install must not create machine config or
# leave a source checkout / DB authority behind.
if [ -e /root/.yoke/config.json ]; then
  echo "unexpected root machine config after installer-only proof" >&2
  exit 1
fi
if [ -n "$USER_HOME" ] && [ -e "$USER_HOME/.yoke/config.json" ]; then
  echo "unexpected user machine config after installer-only proof" >&2
  exit 1
fi

echo "YOKE_INSTALL_TEST_OK $LABEL"
"""


def first_use_browser_script() -> str:
    """Probe that the browser runtime provisions on first use, not at install.

    Run after a clean installer-only proof: ``yoke qa browser setup`` should
    fetch Node/npm/Chromium on demand and then ``status`` should pass.
    """
    return """#!/bin/sh
set -eu

echo "YOKE_BROWSER_FIRST_USE_BEGIN"
# Browser runtime is deferred to first use; this is the on-demand setup.
yoke qa browser setup
yoke qa browser status
echo "YOKE_BROWSER_FIRST_USE_OK"
"""


def prepare_evidence_dir(
    evidence_dir: Path,
    *,
    run_id: str,
    commit_sha: str,
    cells: Sequence[LinuxProofCell] | None = None,
) -> dict[str, object]:
    selected_cells = tuple(cells or linux_proof_cells())
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.chmod(0o700)
    scripts_root = evidence_dir / "scripts"
    scripts_root.mkdir(parents=True, exist_ok=True)
    scripts_root.chmod(0o700)
    scripts_dir = scripts_root / "linux"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir.chmod(0o700)

    script_paths: list[str] = []
    for cell in selected_cells:
        path = scripts_dir / f"{cell.label}.sh"
        path.write_text(render_linux_probe_script(cell), encoding="utf-8")
        path.chmod(0o700)
        script_paths.append(str(path))

    browser_path = scripts_root / "first-use-browser.sh"
    browser_path.write_text(first_use_browser_script(), encoding="utf-8")
    browser_path.chmod(0o700)

    manifest = {
        "run_id": run_id,
        "generated_at": _now_iso(),
        "yoke_commit_sha": commit_sha,
        "secret_marker_denies": list(SECRET_MARKERS),
        "linux_cells": [asdict(cell) for cell in selected_cells],
        "script_paths": script_paths,
        "first_use_browser_script": str(browser_path),
    }
    manifest_path = evidence_dir / "acceptance-inputs.json"
    json_helper._dump_json(manifest_path, manifest)
    manifest_path.chmod(0o600)
    return manifest


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sh_single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


# The argparse driver lives in a sibling module to keep this generation module
# under the authored line limit; it is imported lazily to avoid the import cycle
# (the CLI imports the generation functions above). These re-exports keep
# ``installer_cold_start_proof.{build_parser,main}`` callable as before.
def build_parser():
    from yoke_core.tools.installer_cold_start_proof_cli import build_parser as _bp

    return _bp()


def main(argv: Sequence[str] | None = None) -> int:
    from yoke_core.tools.installer_cold_start_proof_cli import main as _main

    return _main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
