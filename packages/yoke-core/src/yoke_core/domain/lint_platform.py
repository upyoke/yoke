"""Table-driven AST portability scan for code executed on operator machines.

Every hit fails the check. Server image, generated bundle and remote payload
trees are outside this lint. Text I/O requires explicit UTF-8 encoding.
Binary I/O is exempt.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import re
from pathlib import Path

from yoke_core.domain.lint_project_name_literal import is_exempt_relpath

ROOTS = tuple(f"packages/yoke-{name}/src" for name in ("contracts", "cli", "harness", "core")) + (
    "packaging/public-installer",
)
# host_provisioning holds stdlib-only scripts copied onto POSIX test hosts.
EXCLUDED = ("/build/", "/install_bundle_tree/", "/frontend_events/", "/migrations/",
            "/yoke_core/api/", "/yoke_core/ui/", "/yoke_core/db/",
            "/yoke_harness/host_provisioning/")
OWNERS = {
    "fcntl": {"platform_file_lock.py"},
    "process": {"platform_process.py", "platform_process_windows.py"},
    "getuid": {"owner_private_path.py"},
    "symlink": {"platform_links.py"},
    "tmp": {"lint_platform.py", "platform_paths.py"},
}
NON_FILE_IO = {
    "tarfile.open", "PIL.Image.open", "webbrowser.open",
    "yoke_cli.config.onboard_checklist_files.write_text",
}


@dataclass(frozen=True)
class PlatformHit:
    path: str
    line: int
    rule: str


def _name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_name(node.value)}.{node.attr}"
    return ""


def scan_source(source: str, path: str) -> list[PlatformHit]:
    if not re.search(r"\b(fcntl|getuid|symlink_to|read_text|write_text|open|kill|killpg|setsid|preexec_fn|start_new_session|ps)\b|/tmp", source):
        return []
    tree = ast.parse(source, filename=path)
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for entry in node.names:
                aliases[entry.asname or entry.name] = entry.name
        elif isinstance(node, ast.ImportFrom):
            for entry in node.names:
                aliases[entry.asname or entry.name] = f"{node.module}.{entry.name}"
    def name(node):
        value = _name(node)
        first, _, rest = value.partition(".")
        return aliases.get(first, first) + ("." + rest if rest else "")

    # These APIs open a connection, image, archive or terminal, not a text
    # file. Infer receivers from their factories instead of exempting names
    # such as "opener", which could just as well refer to a Path.
    factories = {
        "urllib.request.build_opener": "urllib.request.OpenerDirector",
        "importlib.metadata.distribution": "importlib.metadata.Distribution",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "LinuxTerminal":
            factories[node.name] = "LinuxTerminal"
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Attribute):
            if (node.value.attr == "LinuxTerminal" and isinstance(node.value.value, ast.Call)
                    and name(node.value.value.func).endswith(".get_ssh_linux_terminal")):
                factories.update({_name(t): "LinuxTerminal" for t in node.targets})
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.returns and any(name(n) == "importlib.metadata.Distribution"
                                    for n in ast.walk(node.returns)):
                factories[node.name] = "importlib.metadata.Distribution"
            if any(isinstance(n, ast.Return) and n.value is not None
                   and name(n.value) == "PIL.Image" for n in ast.walk(node)):
                factories[node.name] = "PIL.Image"
    bindings = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            kind = factories.get(name(value.func)) if isinstance(value, ast.Call) else None
            for target in targets:
                if isinstance(target, ast.Name):
                    bindings.setdefault(target.id, set()).add(kind)
    receivers = {key: next(iter(kinds)) for key, kinds in bindings.items()
                 if len(kinds) == 1 and None not in kinds}

    def non_file_io(node, function):
        if function in NON_FILE_IO:
            return True
        if not isinstance(node.func, ast.Attribute):
            return False
        kind = receivers.get(_name(node.func.value))
        return ((node.func.attr == "open" and kind in {
            "urllib.request.OpenerDirector", "PIL.Image", "LinuxTerminal"})
            or (node.func.attr == "read_text" and kind == "importlib.metadata.Distribution"))

    # Only the protected branch of a platform test guards getuid. A getuid in
    # the other branch or later in the function is still an offender.
    guarded = set()
    for node in ast.walk(tree) if "getuid" in source else ():
        if isinstance(node, ast.If):
            text = ast.unparse(node.test)
            safe = ("hasattr(os, 'getuid')" in text or "os.name != 'nt'" in text
                    or "sys.platform != 'win32'" in text)
            if safe:
                guarded.update(id(child) for statement in node.body for child in ast.walk(statement))

    def is_fcntl(node):
        return ((isinstance(node, ast.Import) and any(a.name == "fcntl" for a in node.names))
                or (isinstance(node, ast.ImportFrom) and node.module == "fcntl"))

    def is_process(node):
        if not isinstance(node, ast.Call):
            return False
        function = name(node.func)
        if function in {"os.killpg", "os.setsid"}:
            return True
        if function == "os.kill" and len(node.args) > 1:
            return isinstance(node.args[1], ast.Constant) and node.args[1].value == 0
        if any(k.arg in {"preexec_fn", "start_new_session"} for k in node.keywords):
            return True
        if function.startswith("subprocess.") and node.args:
            argument = node.args[0]
            first = argument.elts[0] if isinstance(argument, (ast.List, ast.Tuple)) and argument.elts else argument
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                return first.value.strip().split(" ")[0].rsplit("/", 1)[-1] == "ps"
        return False

    def is_mode(node):
        return (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and bool(node.value) and set(node.value) <= set("rwxabt+"))

    def text_io(node):
        if not isinstance(node, ast.Call):
            return False
        function = name(node.func)
        tail = function.rsplit(".", 1)[-1]
        if tail not in {"open", "read_text", "write_text"}:
            return False
        if non_file_io(node, function):
            return False
        if function == "os.open":
            return False
        if any(k.arg == "encoding" and not (isinstance(k.value, ast.Constant) and k.value.value is None)
               for k in node.keywords):
            return False
        if tail == "open":
            # builtins open(file, mode) and Path.open(mode) put the mode at different
            # positions, so take the first of args[0:2] that reads as a mode string.
            mode = next((k.value for k in node.keywords if k.arg == "mode"),
                        next((a for a in node.args[:2] if is_mode(a)), None))
            if isinstance(mode, ast.Constant) and isinstance(mode.value, str) and "b" in mode.value:
                return False
            if len(node.args) > 3:  # builtins open's positional encoding
                return False
        return True

    rules = {
        "fcntl": is_fcntl,
        "process": is_process,
        "getuid": lambda n: isinstance(n, ast.Call) and name(n.func) == "os.getuid" and id(n) not in guarded,
        "symlink": lambda n: isinstance(n, ast.Call) and name(n.func).endswith(".symlink_to"),
        "tmp": lambda n: isinstance(n, ast.Constant) and n.value == "/tmp",
        "encoding": text_io,
    }
    hits = []
    filename = Path(path).name
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            candidates = ("fcntl",)
        elif isinstance(node, ast.Call):
            candidates = ("process", "getuid", "symlink", "encoding")
        elif isinstance(node, ast.Constant) and node.value == "/tmp":
            candidates = ("tmp",)
        else:
            continue
        for rule in candidates:
            matches = rules[rule]
            if filename in OWNERS.get(rule, ()) or not matches(node):
                continue
            hits.append(PlatformHit(path, node.lineno, rule))
    return hits


def scan_tree(root: Path) -> list[PlatformHit]:
    hits = []
    for directory in ROOTS:
        for path in sorted((root / directory).rglob("*.py")):
            relative = path.relative_to(root).as_posix()
            if is_exempt_relpath(relative) or any(part in relative for part in EXCLUDED):
                continue
            hits.extend(scan_source(path.read_text(encoding="utf-8"), relative))
    return hits


def findings(root: Path) -> list[str]:
    return [
        f"platform_offender: {hit.path}:{hit.line} {hit.rule}; "
        "Use the shared platform_* helper or explicit UTF-8 encoding."
        for hit in scan_tree(root)
    ]


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    arguments = parser.parse_args()
    errors = findings(arguments.root)
    for finding in errors:
        print(finding)
    return int(bool(errors))


if __name__ == '__main__':
    raise SystemExit(main())
