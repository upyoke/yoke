"""Event-name discovery primitives for the Yoke event platform.

Owns the AST/regex utilities that scan Yoke's source surfaces for
emitter call sites and the ``cmd_registry_discover`` driver that walks
shell scripts, SKILL markdown, and runtime Python under
``runtime/api`` to produce ``"EventName|file/path"`` lines.

The output format is byte-stable: callers in ``populate_registry``
(``_parse_discovery_output``) and in
``yoke_core.domain.events_registry_audit`` (line-splitting in the
audit/diff commands) consume this exact format.

``events_reporting`` re-exports every name in this module so historical
callers continue to import the AST utilities and ``cmd_registry_discover``
from ``yoke_core.domain.events_reporting`` and from
``yoke_core.domain.events_crud``.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path
from typing import List, Optional

__all__ = [
    "_discover_python_event_names",
    "_extract_event_name_from_line",
    "_join_continuation_lines",
    "_py_call_name",
    "_py_string_value",
    "_validate_event_name",
    "cmd_registry_discover",
]


def _py_call_name(node: ast.AST) -> str:
    """Return the terminal function name for a Python call node."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _py_string_value(node: ast.AST) -> Optional[str]:
    """Return a constant string value when the AST node is a string literal."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _validate_event_name(name: str) -> bool:
    """Check PascalCase event name (matches shell _validate_event_name)."""
    if not name:
        return False
    if not name[0].isupper():
        return False
    return bool(re.match(r"^[A-Za-z0-9]+$", name))


def _discover_python_event_names(content: str) -> List[str]:
    """Discover Python-native event names from emitter helpers and parse_args lists."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []

    discovered: List[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        func_name = _py_call_name(node.func)
        if not func_name:
            continue

        if func_name == "parse_args" and node.args:
            argv = node.args[0]
            if isinstance(argv, (ast.List, ast.Tuple)):
                values = [_py_string_value(elt) for elt in argv.elts]
                for idx, value in enumerate(values[:-1]):
                    if value == "--name":
                        event_name = values[idx + 1]
                        if event_name and _validate_event_name(event_name):
                            discovered.append(event_name)
            continue

        is_emitter = (
            func_name == "emit_event"
            or func_name == "_emit_event"
            or (
                func_name.endswith("_event")
                and (func_name.startswith("emit_") or func_name.startswith("_emit_"))
            )
        )
        if not is_emitter:
            continue

        event_name = None
        for kw in node.keywords:
            if kw.arg in ("name", "event_name"):
                candidate = _py_string_value(kw.value)
                if candidate and _validate_event_name(candidate):
                    event_name = candidate
                    break
        if event_name:
            discovered.append(event_name)
            continue

        for arg in node.args:
            candidate = _py_string_value(arg)
            if candidate and _validate_event_name(candidate):
                discovered.append(candidate)
                break

    return discovered


def _extract_event_name_from_line(line: str) -> Optional[str]:
    """Extract --name value from a joined line (handles quotes and bare forms)."""
    for pat in [
        r'--name\s+"([^"]+)"',
        r"--name\s+'([^']+)'",
        r"--name\s+(\S+)",
    ]:
        m = re.search(pat, line)
        if m:
            name = m.group(1)
            if _validate_event_name(name):
                return name
    return None


def _join_continuation_lines(text: str) -> List[str]:
    """Join backslash-continuation lines into single logical lines."""
    lines = text.split("\n")
    result: list[str] = []
    buf = ""
    for line in lines:
        if line.endswith("\\"):
            buf += line[:-1] + " "
        else:
            buf += line
            result.append(buf)
            buf = ""
    if buf:
        result.append(buf)
    return result


def cmd_registry_discover(repo_root: Optional[str] = None) -> str:
    """Discover shell, SKILL, and Python event call sites as event_name|path."""
    if repo_root is None:
        # Try to find repo root
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, check=True,
            )
            repo_root = result.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise RuntimeError("Cannot determine repo root")

    root = Path(repo_root)
    scripts_dir = root / ".agents" / "skills" / "yoke" / "scripts"
    skills_dir = root / ".agents" / "skills" / "yoke"
    api_dir = root / "runtime" / "api"

    found: list[str] = []

    # --- Surface 1: Shell scripts ---
    if scripts_dir.is_dir():
        for sh_file in scripts_dir.rglob("*.sh"):
            if "/tests/" in str(sh_file):
                continue
            try:
                content = sh_file.read_text(errors="replace")
            except OSError:
                continue
            if "emit-event" not in content:
                continue
            rel = str(sh_file.relative_to(root))

            # Standard --name extraction from joined lines
            for joined in _join_continuation_lines(content):
                if "--name" not in joined:
                    continue
                stripped = joined.lstrip()
                if stripped.startswith("#"):
                    continue
                if "sh " not in joined:
                    continue
                # Skip string literals
                if "print(" in joined or "+ sq +" in joined or ("printf " in joined and "emit-event" in joined):
                    continue
                ename = _extract_event_name_from_line(joined)
                if ename:
                    found.append(f"{ename}|{rel}")

            # Variable-assigned event names
            for line in content.split("\n"):
                m = re.search(r'_event_name="([A-Z][A-Za-z0-9]*)"', line)
                if m and _validate_event_name(m.group(1)):
                    found.append(f"{m.group(1)}|{rel}")

        # observe-tool.sh Python-embedded emitters
        observe_file = scripts_dir / "observe-tool.sh"
        if observe_file.is_file():
            obs_rel = str(observe_file.relative_to(root))
            try:
                content = observe_file.read_text(errors="replace")
            except OSError:
                content = ""
            for line in content.split("\n"):
                if "event_name = " in line:
                    # Extract quoted event names from Python assignments
                    normalized = line.replace("'", '"')
                    for m in re.finditer(r'"([A-Z][a-zA-Z]*)"', normalized):
                        if _validate_event_name(m.group(1)):
                            found.append(f"{m.group(1)}|{obs_rel}")

        # deploy-pipeline.sh was deleted in zero-shell wave 3;
        # its emit_run_event calls now live in
        # yoke_core.domain.deploy_pipeline and are picked up by Surface 3
        # (API Python files) below.

    # --- Surface 2: SKILL .md files ---
    if skills_dir.is_dir():
        for md_file in skills_dir.rglob("*.md"):
            if "/tests/" in str(md_file) or "/scripts/" in str(md_file):
                continue
            try:
                content = md_file.read_text(errors="replace")
            except OSError:
                continue
            if "emit-event" not in content:
                continue
            rel = str(md_file.relative_to(root))
            for joined in _join_continuation_lines(content):
                if "--name" not in joined:
                    continue
                ename = _extract_event_name_from_line(joined)
                if ename:
                    found.append(f"{ename}|{rel}")

    # --- Surface 3: API Python files ---
    if api_dir.is_dir():
        for py_file in api_dir.rglob("*.py"):
            rel_py = str(py_file.relative_to(root))
            if "/test" in rel_py:
                continue
            try:
                content = py_file.read_text(errors="replace")
            except OSError:
                continue
            if not any(
                marker in content
                for marker in ("emit-event", "emit_event", "_emit_", "parse_args", "EVENT_")
            ):
                continue
            rel = str(py_file.relative_to(root))

            for event_name in _discover_python_event_names(content):
                found.append(f"{event_name}|{rel}")

            for line in content.split("\n"):
                if '"--name"' in line:
                    m = re.search(r'"--name",\s*"([^"]+)"', line)
                    if m and _validate_event_name(m.group(1)):
                        found.append(f"{m.group(1)}|{rel}")

            # Python constant definitions
            for line in content.split("\n"):
                m = re.match(r'^EVENT_.*=\s*"([A-Z][A-Za-z0-9]*)"', line)
                if m and _validate_event_name(m.group(1)):
                    found.append(f"{m.group(1)}|{rel}")

    return "\n".join(found)
