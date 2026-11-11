"""Run rendered shell fragments with fault-injected tools and shortened clocks."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def shell_functions(script: str) -> str:
    """Keep the installed helpers without executing host provisioning."""
    patterns = [
        r"^fail\(\).*?$",
        r"^APT_TIMEOUT_SECONDS=.*?$",
        r"^apt_get\(\) \{.*?^\}",
        r"^fetch\(\) \{.*?^\}",
    ]
    return "\n".join(
        match.group() for pattern in patterns
        for match in re.finditer(pattern, script, re.M | re.S if ".*?^" in pattern else re.M)
    ) + "\n"


def run_fragment(tmp_path: Path, script: str, mode: str):
    tools = tmp_path / "tools"
    tools.mkdir(exist_ok=True)
    log = tmp_path / "calls"
    # Exercise real subprocess termination, shortening only the clock. Preserve
    # and record the shipped timeout arguments so their bounds are also checked.
    timeout = tools / "timeout"
    timeout.write_text(
        f"#!{sys.executable}\n"
        "import os, subprocess, sys\n"
        "args=sys.argv[1:]\n"
        "with open(os.environ['CALLS'], 'a') as f: f.write('timeout '+repr(args)+'\\n')\n"
        "assert args.pop(0) == '--kill-after=10'\n"
        "assert args.pop(0) in ('180', '600')\n"
        "limit = 0.25 if os.environ['FETCH_MODE'] == 'hung' else 10\n"
        "try: sys.exit(subprocess.run(args, timeout=limit).returncode)\n"
        "except subprocess.TimeoutExpired: sys.exit(124)\n"
    )
    timeout.chmod(0o755)
    for name in ["apt-get", "curl", "pip", "npm", "npx", "dnf", "sudo", "sh"]:
        tool = tools / name
        if name == "sudo":
            body = 'exec "$@"\n'
        else:
            body = (
                'echo "$0 $*" >> "$CALLS"\n'
                'case "$FETCH_MODE" in\n'
                '  success) exit 0;;\n'
                '  unreachable) echo "Temporary failure resolving packages.invalid" >&2; exit 6;;\n'
                '  hung) exec sleep 5;;\n'
                'esac\n'
            )
        tool.write_text("#!/bin/bash\n" + body)
        tool.chmod(0o755)
    env = dict(os.environ, PATH=f"{tools}:{os.environ['PATH']}",
               FETCH_MODE=mode, CALLS=str(log))
    result = subprocess.run(
        ["/bin/bash", "-eu", "-o", "pipefail"], input=script,
        text=True, capture_output=True, env=env, timeout=30,
    )
    return result, log.read_text() if log.exists() else ""
