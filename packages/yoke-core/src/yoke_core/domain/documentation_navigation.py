"""The recursive public documentation tree and its canonical web routes."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import subprocess
from typing import Iterator

import yaml
from yaml.tokens import AliasToken, AnchorToken

from yoke_core.domain.yaml_helper import _RejectDuplicateKeys


@dataclass(frozen=True)
class NavNode:
    title: str
    summary: str
    path: str
    children: tuple[NavNode, ...] = ()


@dataclass(frozen=True)
class NavigationRefusal:
    code: str
    target: str
    detail: str
    repair: str

    def __str__(self) -> str:
        message = f"{self.code} {self.target}: {self.detail}. Repair: {self.repair}"
        return message.encode("utf-8", errors="backslashreplace").decode("utf-8")


class NavigationError(ValueError):
    """A tree cannot be loaded; its named refusals carry the repair."""

    def __init__(self, refusals: list[NavigationRefusal]):
        self.refusals = refusals
        super().__init__("\n".join(map(str, refusals)))


class _NavigationLoader(_RejectDuplicateKeys):
    def construct_mapping(self, node, deep=False):
        if any(key.value == "<<" for key, _ in node.value):
            raise ValueError("merge keys are forbidden; spell out each node")
        return super().construct_mapping(node, deep=deep)


def route_for(path: str) -> str:
    """Map a validated Markdown page to its extensionless /docs route."""
    _validate_path(path)
    stem = path[:-3]
    if stem == "index":
        stem = ""
    elif stem.endswith("/index"):
        stem = stem[:-6]
    return "/docs" + ("/" + stem if stem else "")


def _validate_path(path: str) -> None:
    if not isinstance(path, str) or not path:
        raise ValueError("use a non-empty POSIX Markdown path")
    try:
        path.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError("use a UTF-8 page path") from exc
    if path.startswith("/") or ".." in path.split("/"):
        raise ValueError("path escapes the documentation root")
    if (
        "\\" in path
        or "?" in path
        or "#" in path
        or "\x00" in path
        or any(part in ("", ".") for part in path.split("/"))
        or not path.endswith(".md")
    ):
        raise ValueError("use a relative POSIX .md path without query or fragment")


def _tracked_pages(root: Path) -> set[str]:
    """Source docs are git-owned; materialized snapshots are file-owned."""
    root = root.resolve()
    repo = root.parent.parent
    if root == repo / "docs/public" and (repo / ".git").exists():
        tracked = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "-z", "--", "docs/public"],
            capture_output=True,
            check=True,
        )
        return {
            p.removeprefix("docs/public/")
            for p in tracked.stdout.decode("utf-8").split("\x00")
            if p.endswith(".md")
        }
    return {p.relative_to(root).as_posix() for p in root.rglob("*.md") if p.is_file()}


def _read_navigation(root: Path) -> tuple[NavNode | None, list[NavigationRefusal]]:
    refusals: list[NavigationRefusal] = []

    def refuse(code, target, detail, repair):
        refusals.append(NavigationRefusal(code, target, detail, repair))

    try:
        text = (root / "nav.yaml").read_text(encoding="utf-8")
        if any(isinstance(t, (AliasToken, AnchorToken)) for t in yaml.scan(text)):
            refuse(
                "NAV_ALIAS",
                "nav.yaml",
                "anchors and aliases are forbidden",
                "write each node explicitly without anchors or aliases",
            )
            return None, refusals
        data = yaml.load(text, Loader=_NavigationLoader)
    except (OSError, UnicodeError, yaml.YAMLError, ValueError) as exc:
        refuse("NAV_SCHEMA", "nav.yaml", str(exc), "write one valid root mapping")
        return None, refusals
    if not isinstance(data, dict) or set(data) != {"root"}:
        code = (
            "NAV_UNKNOWN_KEY"
            if isinstance(data, dict) and set(data) - {"root"}
            else "NAV_SCHEMA"
        )
        refuse(
            code,
            "nav.yaml",
            "expected exactly the top-level key root",
            "replace the document with a root node",
        )
        return None, refusals
    try:
        tracked = _tracked_pages(root)
    except (OSError, UnicodeError, subprocess.SubprocessError):
        refuse(
            "NAV_SCHEMA",
            "nav.yaml",
            "source page ownership could not be read",
            "restore git access in the source checkout and retry",
        )
        return None, refusals
    seen: set[str] = set()
    routes: dict[str, str] = {}

    def node(raw, ancestors: tuple[str, ...] = ()) -> NavNode | None:
        target = (
            str(raw.get("path", "nav.yaml")) if isinstance(raw, dict) else "nav.yaml"
        )
        if not isinstance(raw, dict):
            refuse(
                "NAV_SCHEMA",
                target,
                "node must be a mapping",
                "supply title, summary and path",
            )
            return None
        unknown = set(raw) - {"title", "summary", "path", "children"}
        if unknown:
            refuse(
                "NAV_UNKNOWN_KEY",
                target,
                f"unknown keys: {sorted(map(str, unknown))}",
                "remove unknown node keys",
            )
        valid = True
        for key in ("title", "summary", "path"):
            if key not in raw:
                refuse(
                    "NAV_SCHEMA", target, f"missing {key}", f"supply a non-empty {key}"
                )
                valid = False
            elif not isinstance(raw[key], str) or not raw[key].strip():
                refuse(
                    "NAV_EMPTY_VALUE",
                    target,
                    f"{key} must be a non-empty string",
                    f"supply a non-empty {key}",
                )
                valid = False
        children = raw.get("children", [])
        if not isinstance(children, list):
            refuse(
                "NAV_SCHEMA",
                target,
                "children must be a list",
                "supply an ordered list of nodes",
            )
            children = []
        if not valid:
            return None
        path = raw["path"]
        try:
            _validate_path(path)
        except ValueError as exc:
            code = (
                "NAV_PATH_ESCAPES"
                if path.startswith("/") or ".." in path.split("/")
                else "NAV_PATH_INVALID"
            )
            refuse(
                code,
                path,
                str(exc),
                "use a relative .md path inside the documentation root",
            )
            return None
        if not (root / path).resolve().is_relative_to(root.resolve()):
            refuse(
                "NAV_PATH_ESCAPES",
                path,
                "page resolves outside the root",
                "move the page inside the documentation root",
            )
        elif path not in tracked or not (root / path).is_file():
            refuse(
                "NAV_PATH_MISSING",
                path,
                "page is missing or untracked",
                "create and git-add the page in source, or include it in the snapshot",
            )
        if path in ancestors:
            refuse(
                "NAV_CYCLE",
                path,
                "page is its own descendant",
                "remove the descendant reference",
            )
        elif path in seen:
            refuse(
                "NAV_DUPLICATE_PAGE",
                path,
                "page has more than one parent",
                "keep the page at one location in the tree",
            )
        seen.add(path)
        if children and PurePosixPath(path).name != "index.md":
            refuse(
                "NAV_CATEGORY_NOT_INDEX",
                path,
                "category is not an index page",
                "give the category an index.md page",
            )
        route = route_for(path)
        if route in routes and routes[route] != path:
            refuse(
                "NAV_ROUTE_COLLISION",
                path,
                f"route {route} also belongs to {routes[route]}",
                "choose distinct page and category routes",
            )
        routes[route] = path
        parsed = tuple(
            child
            for value in children
            if (child := node(value, ancestors + (path,))) is not None
        )
        return NavNode(raw["title"], raw["summary"], path, parsed)

    tree = node(data["root"])
    if tree and tree.path != "index.md":
        refuse(
            "NAV_PATH_INVALID",
            tree.path,
            "root path must be index.md",
            "set root.path to index.md",
        )
    return tree, refusals


def load_navigation(root: Path) -> NavNode:
    tree, refusals = _read_navigation(Path(root))
    if refusals:
        raise NavigationError(refusals)
    assert tree is not None
    return tree


def iter_nodes(node: NavNode) -> Iterator[NavNode]:
    yield node
    for child in node.children:
        yield from iter_nodes(child)


def breadcrumbs(tree: NavNode, path: str) -> list[NavNode]:
    if tree.path == path:
        return [tree]
    for child in tree.children:
        if found := breadcrumbs(child, path):
            return [tree, *found]
    return []


def immediate_children(tree: NavNode, path: str) -> list[NavNode]:
    found = breadcrumbs(tree, path)
    return list(found[-1].children) if found else []


def validate_navigation(root: Path, *, complete: bool) -> list[NavigationRefusal]:
    tree, refusals = _read_navigation(Path(root))
    if complete and tree:
        listed = {node.path for node in iter_nodes(tree)}
        refusals.extend(
            NavigationRefusal(
                "UNLISTED_PAGE",
                path,
                "page is absent from navigation",
                "add the page to nav.yaml under its canonical parent",
            )
            for path in sorted(_tracked_pages(Path(root)) - listed)
        )
    return refusals


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check"])
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument(
        "--partial",
        action="store_true",
        help="allow pages not yet listed in navigation",
    )
    args = parser.parse_args(argv)
    refusals = validate_navigation(args.root, complete=not args.partial)
    for refusal in refusals:
        print(refusal)
    if not refusals:
        print(
            f"Navigation OK: {sum(1 for _ in iter_nodes(load_navigation(args.root)))} pages"
        )
    return int(bool(refusals))


if __name__ == "__main__":
    raise SystemExit(main())
