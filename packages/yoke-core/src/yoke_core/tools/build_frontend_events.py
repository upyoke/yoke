"""Build shipped workbench modules from the project's installed Events Pack.

Run after Pack adoption/update. Python gets package-relative sibling imports;
browser modules have types stripped by Node and load ordinary JS rule data.
This build does not fetch or install a Pack and never changes its baseline.
"""

import argparse
import json
import re
import subprocess
from pathlib import Path

from yoke_core.domain.workspace_authority import (
    assert_target_under_session_work_authority,
)

BROWSER_MODULES = (
    "events",
    "events_attribution",
    "events_capture",
    "events_navigation",
    "events_props",
    "events_types",
)
SERVER_MODULES = (
    "events_attribution",
    "events_cookie",
    "events_device",
    "events_handoff",
)
HEADER = "// Generated from the installed structured-events Pack; run build_frontend_events.\n"
PYTHON_HEADER = "# Generated from the installed structured-events Pack; run build_frontend_events.\n"
NODE_STRIP = """
import { stripTypeScriptTypes } from 'node:module';
let text = '';
for await (const chunk of process.stdin) text += chunk;
process.stdout.write(stripTypeScriptTypes(text, { mode: 'strip' }));
"""


def outputs(root):
    source = root / "events"
    target = root / "packages/yoke-core/src/yoke_core"
    if not (source / "events_capture.ts").is_file():
        raise ValueError(
            "events_pack_not_installed: install structured-events with yoke packs update, then rebuild"
        )
    result = {}
    for name in BROWSER_MODULES:
        original = (source / f"{name}.ts").read_text()
        stripped = subprocess.run(
            ["node", "--input-type=module", "-e", NODE_STRIP],
            input=original,
            text=True,
            capture_output=True,
            check=True,
        ).stdout
        stripped = re.sub(r"(['\"])\./([^'\"]+)\.ts\1", r"\1./\2.js\1", stripped)
        stripped = re.sub(
            r"import rules from './attribution_rules.json' with \{ type: 'json' \};",
            "import rules from './attribution_rules.js';",
            stripped,
        )
        result[target / "ui/static" / f"{name}.js"] = HEADER + stripped
    rules = json.loads((source / "attribution_rules.json").read_text())
    result[target / "ui/static/attribution_rules.js"] = (
        HEADER + "export default " + json.dumps(rules, separators=(",", ":")) + ";\n"
    )
    for name in SERVER_MODULES:
        text = (source / f"{name}.py").read_text()
        text = re.sub(
            r"^from (events_\w+) import", r"from .\1 import", text, flags=re.M
        )
        result[target / "frontend_events" / f"{name}.py"] = PYTHON_HEADER + text
    # Standalone timestamp resources retain the installed Pack's exact bytes.
    result[target / "ui/static/events_timestamps.mjs"] = (
        source / "events_timestamps.mjs"
    ).read_text()
    result[target / "frontend_events/events_timestamps.py"] = (
        source / "events_timestamps.py"
    ).read_text()
    result[target / "frontend_events/attribution_rules.json"] = (
        source / "attribution_rules.json"
    ).read_text()
    result[target / "frontend_events/__init__.py"] = (
        '"""Runtime helpers built from the installed Structured Events Pack."""\n'
    )
    return result


def build(*, target_root: Path, check: bool = False):
    expected = outputs(target_root)
    drift = []
    for path, text in expected.items():
        if path.exists() and path.read_text() == text:
            continue
        drift.append(path.relative_to(target_root).as_posix())
        if not check:
            assert_target_under_session_work_authority(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    if check and drift:
        print(
            "frontend_events_build_stale: run python3 -m yoke_core.tools.build_frontend_events; "
            + ", ".join(drift)
        )
        return 1
    print(
        f"frontend events build: {len(expected)} files; {len(drift)} {'stale' if check else 'updated'}"
    )
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        return build(target_root=args.root.resolve(), check=args.check)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(
            f"frontend_events_build_failed: {error}; install the Pack and Node >=22.13, then rebuild"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
