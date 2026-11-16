"""Table-driven AST portability scan for code executed on operator machines.

Known offenders are a shrink-only ratchet, keyed by path/rule/AST fingerprint,
not line numbers. Move callers to platform_* owners and delete their entries;
never add allowances. Server image, generated bundle and remote payload trees
are outside this lint. Text I/O defaults to UTF-8 explicitly; binary I/O is exempt.
"""
from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import re
from pathlib import Path

from yoke_core.domain.lint_project_name_literal import is_exempt_relpath

ROOTS = tuple(f"packages/yoke-{name}/src" for name in ("contracts", "cli", "harness", "core"))
EXCLUDED = ("/build/", "/install_bundle_tree/", "/frontend_events/", "/migrations/",
            "/yoke_core/api/", "/yoke_core/ui/", "/yoke_core/db/")
OWNERS = {
    "fcntl": {"platform_file_lock.py"},
    "process": {"platform_process.py", "platform_process_windows.py"},
    "getuid": {"owner_private_path.py"},
    "symlink": {"platform_links.py"},
    "tmp": {"lint_platform.py"},
}
BASELINE = "packages/yoke-core/src/yoke_core/domain/lint_platform_offenders.json"
RECOVERY = "Use the shared platform_* helper or explicit UTF-8 encoding; remove the fixed offender entry. Never grow the baseline."


@dataclass(frozen=True)
class PlatformHit:
    path: str
    line: int
    rule: str
    fingerprint: str

    @property
    def key(self):
        return f"{self.path}|{self.rule}|{self.fingerprint}"


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

    def text_io(node):
        if not isinstance(node, ast.Call):
            return False
        function = name(node.func)
        tail = function.rsplit(".", 1)[-1]
        if tail not in {"open", "read_text", "write_text"}:
            return False
        if function == "os.open":
            return False
        if any(k.arg == "encoding" and not (isinstance(k.value, ast.Constant) and k.value.value is None)
               for k in node.keywords):
            return False
        if tail == "open":
            mode = next((k.value for k in node.keywords if k.arg == "mode"),
                        node.args[1] if len(node.args) > 1 else None)
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
            fingerprint = hashlib.sha256(ast.dump(node).encode("utf-8")).hexdigest()[:16]
            hits.append(PlatformHit(path, node.lineno, rule, fingerprint))
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


def read_baseline(path: Path) -> Counter:
    """Read path-grouped sites; fingerprints and counts are line-independent."""
    grouped = json.loads(path.read_text(encoding="utf-8"))
    return Counter({f"{path}|{site}": count
                    for path, sites in grouped.items() for site, count in sites.items()})


def _write_baseline(path: Path, counts: Counter) -> None:
    grouped = {}
    for key, count in sorted(counts.items()):
        relative, site = key.split("|", 1)
        grouped.setdefault(relative, {})[site] = count
    rows = ["  " + json.dumps(relative) + ": " + json.dumps(sites, sort_keys=True)
            for relative, sites in grouped.items()]
    path.write_text("{\n" + ",\n".join(rows) + "\n}\n", encoding="utf-8")


def ratchet_findings(root: Path, *, prune: bool = False) -> list[str]:
    baseline = read_baseline(root / BASELINE)
    current = Counter(hit.key for hit in scan_tree(root))
    if prune:
        baseline &= current  # This operation can only remove sites or lower counts.
        _write_baseline(root / BASELINE, baseline)
    new = current - baseline
    stale = baseline - current
    return ([f"new_platform_offender: {key} ({count}); {RECOVERY}" for key, count in sorted(new.items())]
            + [f"stale_platform_offender: {key} ({count}); delete this allowance" for key, count in sorted(stale.items())])


def main() -> int:
    """Run the ratchet; --prune removes fixed entries and can never add any."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--prune', action='store_true', help='Remove fixed allowances; never add new ones')
    arguments = parser.parse_args()
    findings = ratchet_findings(arguments.root, prune=arguments.prune)
    for finding in findings:
        print(finding)
    return int(bool(findings))


if __name__ == '__main__':
    raise SystemExit(main())
