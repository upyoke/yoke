"""Author the project Machine QA case roster from declared candidate artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import tarfile


def cases(
    driver: Path, wheels: Path, versions: dict, versions_file: Path
) -> list[dict]:
    rows = []
    for harness in ("claude", "codex", "cursor"):
        native_versions = versions[harness]
        if not native_versions or set(native_versions) - {"Linux", "Darwin"}:
            raise ValueError("Declare exact Linux/Darwin CLI versions for each harness")
        command = shlex.join(
            [
                "python3",
                "/tmp/yoke-real-harness.py",
                "--harness",
                harness,
                "--versions-file",
                "/tmp/yoke-harness-versions.json",
                "--wheels",
                "/tmp/yoke-harness-wheels.tar",
            ]
        )
        rows.append(
            {
                "case_key": f"native-{harness}-hooks",
                "method_id": "terminal-check",
                "instructions": (
                    "Reset to the signed-in golden, install candidate wheels and onboard "
                    "a disposable local project with GitHub disabled. Launch native status "
                    "and read-only denied-help probes; judge recorded Yoke evidence only."
                ),
                "expected_outcome": (
                    "Each native probe registers exactly one session with the declared "
                    "executor/workspace; evaluated native hooks record allow and deny "
                    "decisions. Native model text and CLI exit alone cannot pass."
                ),
                "host_baselines": ["shell-preconfigured"],
                "entry_surface": command,
                "required_completion": "proved",
                "method_config": {
                    "execution_mode": "terminal-multiplexer",
                    "actions": [
                        {
                            "step": "proved",
                            "keys": [],
                            "capture": False,
                            "ready_text": ["REAL_HARNESS_STARTED"],
                            "ready_timeout_seconds": 300,
                            "completion_text": ["REAL_HARNESS_COMPLETE"],
                        }
                    ],
                    "capture_checkpoints": [],
                    "expected_return_codes": [0],
                    "expected_text": ["REAL_HARNESS_PROVED", '"ok": true'],
                    "max_wall_seconds": 1800,
                    "notes": (
                        "OS-selected bridge: tmux transcript on Linux, GUI Terminal on "
                        "macOS so login-keychain authentication has its real session context. "
                        "Candidate wheels are local artifacts; no credentials are staged."
                    ),
                    "post_checks": ["secret_free"],
                    "setup_operations": [],
                    "start_delay": 0,
                    "step_delay": 0,
                    "stage_files": [
                        {
                            "source_path": str(driver),
                            "remote_path": "/tmp/yoke-real-harness.py",
                        },
                        {
                            "source_path": str(wheels),
                            "remote_path": "/tmp/yoke-harness-wheels.tar",
                        },
                        {
                            "source_path": str(versions_file),
                            "remote_path": "/tmp/yoke-harness-versions.json",
                        },
                    ],
                },
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel-dir", type=Path, required=True)
    parser.add_argument("--wheel-archive", type=Path, required=True)
    parser.add_argument("--versions-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    built = sorted(args.wheel_dir.glob("*.whl"))
    if len(built) != 5:
        parser.error(
            "candidate_wheels_missing: build all five product wheels before authoring"
        )
    with tarfile.open(args.wheel_archive, "w") as archive:
        for wheel in built:
            archive.add(wheel, arcname=wheel.name)
    versions = json.loads(args.versions_file.read_text(encoding="utf-8"))
    args.output.write_text(
        json.dumps(
            cases(
                Path(__file__).with_name("real_harness.py").resolve(),
                args.wheel_archive.resolve(),
                versions,
                args.versions_file.resolve(),
            ),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
