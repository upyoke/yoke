"""Declarative OS scopes, pre-import module selection and source enforcement."""
from __future__ import annotations

import ast
from pathlib import Path
import re
import subprocess
import sys

import pytest

SCOPES = {
    "posix_only": {"linux", "darwin", "freebsd", "aix"},
    "windows_only": {"win32"},
    "macos_only": {"darwin"},
    "linux_only": {"linux"},
}


def scope_allows(name: str, platform: str) -> bool:
    return platform != "win32" if name == "posix_only" else platform in SCOPES[name]


def _validate(scopes, windows=False):
    if len(scopes) > 1:
        raise pytest.UsageError("os_scope_conflict: use exactly one OS scope per test")
    for name, args, kwargs in scopes:
        reason = kwargs.get("reason", args[0] if len(args) == 1 else None)
        if (len(args) > 1 or set(kwargs) - {"reason"} or
                (args and kwargs) or not isinstance(reason, str) or not reason.strip()):
            raise pytest.UsageError(f"os_scope_reason_required: {name} needs one nonempty reason")
        if windows and name != "windows_only":
            raise pytest.UsageError(f"os_scope_windows_conflict: {name} cannot carry windows smoke; remove windows")
        return name, reason
    return None


def _marker_name(node):
    if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute)
            and node.value.attr == "mark" and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "pytest"):
        return node.attr
    return None


def _source_marks(nodes, aliases=None):
    scopes, windows = [], False
    for node in nodes:
        if isinstance(node, ast.Name) and node.id in (aliases or {}):
            own, smoke = _source_marks([aliases[node.id]])
        elif isinstance(node, (ast.List, ast.Tuple)):
            own, smoke = _source_marks(node.elts, aliases)
        else:
            name = _marker_name(node.func if isinstance(node, ast.Call) else node)
            own, smoke = [], name == "windows"
            if name in SCOPES:
                try:
                    args = [ast.literal_eval(a) for a in node.args] if isinstance(node, ast.Call) else []
                    kwargs = {k.arg: ast.literal_eval(k.value) for k in node.keywords} if isinstance(node, ast.Call) else {}
                except (ValueError, TypeError):
                    raise pytest.UsageError(f"os_scope_reason_required: {name} needs a literal reason") from None
                own.append((name, args, kwargs))
        scopes.extend(own)
        windows |= smoke
    return scopes, windows


def _parameter_marks(decorators, aliases):
    for decorator in decorators:
        for node in ast.walk(decorator):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "pytest" and node.func.attr == "param"):
                for keyword in node.keywords:
                    if keyword.arg == "marks":
                        yield _source_marks([keyword.value], aliases)


def _aliases(tree):
    return {target.id: node.value for node in tree.body if isinstance(node, ast.Assign)
            and _source_marks([node.value])[0] for target in node.targets
            if isinstance(target, ast.Name)}


def module_marks(tree):
    return _source_marks([
        node.value for node in tree.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and any(isinstance(t, ast.Name) and t.id == "pytestmark"
                for t in (node.targets if isinstance(node, ast.Assign) else [node.target]))
    ], _aliases(tree))


@pytest.hookimpl(tryfirst=True)
def pytest_pycollect_makemodule(module_path: Path, parent):
    """Validate module scopes before import, even when the module cannot import here."""
    file_path = module_path
    if file_path.suffix != ".py" or not file_path.name.startswith("test_"):
        return None
    tree = ast.parse(file_path.read_bytes(), filename=str(file_path))
    scopes, windows = module_marks(tree)
    scope = _validate(scopes, windows)
    def validate_tests(nodes, inherited, smoke):
        for node in nodes:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                own, selected = _source_marks(node.decorator_list, _aliases(tree))
                _validate(inherited + own, smoke or selected)
                for parameter, chosen in _parameter_marks(node.decorator_list, _aliases(tree)):
                    _validate(inherited + own + parameter, smoke or selected or chosen)
                if isinstance(node, ast.ClassDef):
                    validate_tests(node.body, inherited + own, smoke or selected)
    validate_tests(tree.body, scopes, windows)
    if scope and not scope_allows(scope[0], sys.platform):
        return _ScopedModule.from_parent(parent, path=file_path, scope=scope)
    return None


class _ScopedModule(pytest.Module):
    def __init__(self, *args, scope, **kwargs):
        super().__init__(*args, **kwargs)
        self.scope = scope

    def collect(self):
        pytest.skip(f"{self.scope[0]}: {self.scope[1]}", allow_module_level=True)


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    for item in items:
        scopes = [(m.name, m.args, m.kwargs) for m in item.iter_markers() if m.name in SCOPES]
        scope = _validate(scopes, item.get_closest_marker("windows") is not None)
        if scope and not scope_allows(scope[0], sys.platform):
            item.add_marker(pytest.mark.skip(reason=f"{scope[0]}: {scope[1]}"))


def _os_condition(node, aliases):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        try:
            return _os_condition(ast.parse(node.value, mode="eval"), aliases)
        except SyntaxError:
            return False
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and (child.id in aliases or
                re.search(r"(?:^|_)(WINDOWS|POSIX|DARWIN|LINUX)(?:_|$)", child.id, re.I)):
            return True
        if isinstance(child, ast.Attribute):
            if child.attr.upper() in {"WINDOWS", "POSIX", "DARWIN", "LINUX"}:
                return True
            if isinstance(child.value, ast.Name) and (child.value.id, child.attr) in {
                ("os", "name"), ("sys", "platform"), ("platform", "system")
            }:
                return True
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == "hasattr":
            if any(isinstance(a, ast.Constant) and a.value in {"AF_UNIX", "symlink"} for a in child.args):
                return True
    return False


_OS_TOOL_MODULES = frozenset({
    "fcntl", "grp", "msvcrt", "posix", "pwd", "pywintypes", "resource", "spwd",
    "termios", "tty", "win32api", "win32com", "win32con", "win32file", "win32job",
    "win32process", "win32security", "winreg", "winsound",
})


# yoke-suite.yml provisions these before running native shards. Other jobs
# may use external Postgres or exercise the Python-only search backend.
_NATIVE_SUITE_TOOLS = frozenset({"initdb", "rg"})


def _provisioned(arg):
    return isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value in _NATIVE_SUITE_TOOLS


def _tool_gate(node, names):
    return any(
        (isinstance(child, ast.Name) and child.id in names)
        or (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
            and child.func.attr == "which" and ast.unparse(child.func.value).split(".")[-1] == "shutil"
            and not (child.args and _provisioned(child.args[0])))
        for child in ast.walk(node)
    )


def _tool_skips(tree):
    """Check executable lookup and native-module gates in their declared OS scope."""
    names = {alias.asname or alias.name for node in ast.walk(tree)
             if isinstance(node, ast.ImportFrom) and node.module == "shutil"
             for alias in node.names if alias.name == "which"}
    nodes = list(ast.walk(tree))
    while True:
        discovered = {target.id for node in nodes if isinstance(node, (ast.Assign, ast.AnnAssign))
                      and node.value is not None and _tool_gate(node.value, names)
                      for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
                      if isinstance(target, ast.Name)}
        discovered |= {node.name for node in nodes if isinstance(node, ast.FunctionDef)
                       and any(isinstance(child, ast.Return) and child.value is not None
                               and _tool_gate(child.value, names) for child in ast.walk(node))}
        if discovered <= names:
            break
        names |= discovered

    parents = {child: node for node in nodes for child in ast.iter_child_nodes(node)}
    aliases = _aliases(tree)
    has_module_scope = bool(module_marks(tree)[0])
    hits = set()
    for node in nodes:
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        gated = (
            node.func.attr == "importorskip"
            and node.args and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and node.args[0].value.split(".")[0] in _OS_TOOL_MODULES
        )
        if _marker_name(node.func) in {"skipif", "xfail"}:
            conditions = node.args[:1] or [k.value for k in node.keywords if k.arg == "condition"]
            gated = any(_tool_gate(condition, names) for condition in conditions)
        scoped = has_module_scope
        parent = parents.get(node)
        while parent is not None and not scoped:
            if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                scoped = bool(_source_marks(parent.decorator_list, aliases)[0])
            if isinstance(parent, ast.If) and node.func.attr in {"skip", "skipTest", "xfail"}:
                gated |= _tool_gate(parent.test, names)
            parent = parents.get(parent)
        if gated and not scoped:
            hits.add(node.lineno)
    return hits


def handwritten_os_skips(source: str) -> list[int]:
    tree = ast.parse(source)
    aliases = set()
    while True:
        found = {target.id for node in ast.walk(tree) if isinstance(node, ast.Assign)
                 and _os_condition(node.value, aliases) for target in node.targets
                 if isinstance(target, ast.Name)}
        if found <= aliases:
            break
        aliases |= found
    hits = _tool_skips(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            condition = node.args[0] if node.args else next(
                (k.value for k in node.keywords if k.arg == "condition"), None)
            if (_marker_name(node.func) in {"skipif", "xfail"} and condition is not None
                    and _os_condition(condition, aliases)):
                hits.add(node.lineno)
        if isinstance(node, ast.If) and _os_condition(node.test, aliases):
            for child in ast.walk(node):
                if (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                        and child.func.attr in {"skip", "xfail"}
                        and isinstance(child.func.value, ast.Name) and child.func.value.id == "pytest"):
                    hits.add(child.lineno)
    return sorted(hits)


def scan_tracked(root: Path) -> list[str]:
    paths = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "runtime/**/*.py", "runtime/*.py", "tests/**/*.py", "tests/*.py"],
        cwd=root,
    ).decode().split("\0")
    return [f"{path}:{line}" for path in paths if path
            for line in handwritten_os_skips((root / path).read_text(encoding="utf-8"))]
