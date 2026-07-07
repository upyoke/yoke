"""Codex harness entry launcher — identity resolution and command routing.

Extracted from the former ``yoke-entry.sh`` wrapper. Handles manifest reading,
identity initialization, environment export rendering, bootstrap delegation,
and command routing for the Codex harness.

Can be used as a module or invoked via CLI, for example:
``python3 -m runtime.harness.codex.codex_entry bootstrap``.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Optional

from yoke_core.domain.harness_capability_registry import (
    compact_entrypoint_display,
    shared_downstream_paths,
    shared_entrypoints,
)


def resolve_root() -> Path:
    """Resolve the Yoke repo root."""
    env_root = os.environ.get("YOKE_ROOT", "")
    if env_root:
        return Path(env_root)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        print(
            "Error: not in a git repository. Run from the Yoke repo root.",
            file=sys.stderr,
        )
        sys.exit(1)


def manifest_read(manifest_path: Path, dotpath: str) -> str:
    """Read a dot-separated path from the Codex manifest JSON."""
    if not manifest_path.is_file():
        return ""
    try:
        with manifest_path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        for part in dotpath.split("."):
            if not isinstance(value, dict):
                return ""
            value = value.get(part, "")
        if isinstance(value, list):
            return ",".join(str(item) for item in value)
        if value is None:
            return ""
        return str(value)
    except Exception:
        return ""


def resolve_runtime_model(root: Path) -> str:
    """Resolve the runtime model using the codex_model module."""
    from runtime.harness.codex.codex_model import resolve

    model = resolve()
    return model or ""


class CodexIdentity:
    """Resolved Codex session identity."""

    def __init__(self, root: Path):
        self.root = root
        self.manifest_path = root / "runtime" / "harness" / "codex" / "manifest.json"
        self.bootstrap_spec = root / "runtime" / "harness" / "bootstrap-spec.json"

        manifest_executor = manifest_read(self.manifest_path, "identity.executor")
        if not manifest_executor:
            manifest_executor = "codex"

        runtime_model = resolve_runtime_model(root)

        self.executor = os.environ.get("YOKE_EXECUTOR", manifest_executor)
        self.provider = os.environ.get("YOKE_PROVIDER", "openai")
        self.model = os.environ.get("YOKE_MODEL", runtime_model)

        os.environ["YOKE_EXECUTOR"] = self.executor
        os.environ["YOKE_PROVIDER"] = self.provider
        os.environ["YOKE_MODEL"] = self.model

    def entrypoints(self) -> str:
        """Shared Yoke operator entrypoints."""
        return compact_entrypoint_display(shared_entrypoints())

    def downstream_paths(self) -> str:
        """Shared Yoke downstream paths supported by this adapter."""
        return ", ".join(shared_downstream_paths())

    def display_model(self) -> str:
        return self.model if self.model else "(unresolved)"


def show_env(identity: CodexIdentity) -> None:
    """Print sourceable shell exports."""
    print(f"export YOKE_EXECUTOR={shlex.quote(identity.executor)}")
    print(f"export YOKE_PROVIDER={shlex.quote(identity.provider)}")
    print(f"export YOKE_MODEL={shlex.quote(identity.model)}")
    print(f"export YOKE_ROOT={shlex.quote(str(identity.root))}")


def do_bootstrap(identity: CodexIdentity) -> None:
    """Print full bootstrap orientation context."""
    if not identity.manifest_path.is_file():
        print(
            f"yoke-entry: manifest not found at {identity.manifest_path}",
            file=sys.stderr,
        )
        sys.exit(1)
    if not identity.bootstrap_spec.is_file():
        print(
            f"yoke-entry: bootstrap spec not found at {identity.bootstrap_spec}",
            file=sys.stderr,
        )
        sys.exit(1)

    from runtime.harness.bootstrap import load_spec, render_full

    spec = load_spec(identity.bootstrap_spec)

    print("--- Yoke Bootstrap (Codex wrapper-only) ---")
    print()
    print(render_full(identity.root, spec, extra_files=["CODEX.md"]).rstrip("\n"))
    print(f"--- Bootstrap complete. YOKE_EXECUTOR={identity.executor} ---")
    print(f"--- Provider: {identity.provider} ---")
    print(f"--- Model: {identity.display_model()} ---")
    print(f"--- Supported paths: {identity.downstream_paths()} ---")
    print("--- Use 'python3 -m runtime.harness.codex.codex_entry env' to emit sourceable exports. ---")
    print("--- Use 'python3 -m runtime.harness.codex.codex_entry help' for available commands. ---")


def _identity_block(identity: CodexIdentity) -> str:
    """Common identity block for route commands."""
    lines = [
        f"YOKE_EXECUTOR={identity.executor}",
        f"YOKE_PROVIDER={identity.provider}",
        f"YOKE_MODEL={identity.display_model()}",
        "# YOKE_SUPPORTED_PATHS removed — capabilities derived server-side",
        "",
        "This launcher prints the Codex identity contract; it does not mutate",
        "the parent shell or prompt runtime after it exits.",
        "",
        "For shell-managed wrappers, load the exports first:",
        '  eval "$(python3 -m runtime.harness.codex.codex_entry env)"',
    ]
    return "\n".join(lines)


def route_idea(identity: CodexIdentity, args: list[str]) -> None:
    """Route /yoke idea command."""
    if not args:
        print('yoke-entry: usage: python3 -m runtime.harness.codex.codex_entry idea "title"', file=sys.stderr)
        sys.exit(1)
    print(_identity_block(identity))
    title = " ".join(args)
    print()
    print("To file a new idea, use the /yoke idea operator command:")
    print(f"  /yoke idea {title}")
    print()
    print(
        "The Codex session should invoke this as a prompt-level command using"
    )
    print("the identity values shown above.")


def route_do(identity: CodexIdentity) -> None:
    """Route /yoke do command."""
    print(_identity_block(identity))
    print()
    print("To start an autonomous session, use the /yoke do operator command:")
    print("  /yoke do")
    print()
    print("The session offer will include:")
    print(f"  executor:        {identity.executor}")
    print(f"  provider:        {identity.provider}")
    print(f"  model:           {identity.display_model()}")
    print(f"  supported_paths: {identity.downstream_paths()}")
    print()
    print("Downstream paths not in the derived set will fall back truthfully.")


def route_refine(identity: CodexIdentity, args: list[str]) -> None:
    """Route /yoke refine command."""
    if not args:
        print(
            "yoke-entry: usage: python3 -m runtime.harness.codex.codex_entry refine YOK-N", file=sys.stderr
        )
        sys.exit(1)
    print(_identity_block(identity))
    item = " ".join(args)
    print()
    print("To refine item artifacts directly in Codex, use:")
    print(f"  /yoke refine {item}")
    print()
    print("Refine is a standalone operator entrypoint. It does not depend on")
    print("the /yoke do session-offer loop or supported_paths routing.")


def route_advance(identity: CodexIdentity, args: list[str]) -> None:
    """Route /yoke advance implementation command."""
    if not args or "implementation" not in args:
        print(
            "yoke-entry: usage: python3 -m runtime.harness.codex.codex_entry advance YOK-N implementation",
            file=sys.stderr,
        )
        sys.exit(1)
    print(_identity_block(identity))
    item = " ".join(args)
    print()
    print("This wrapper displays guidance only -- it does not claim the item,")
    print("create a worktree, update status, or start implementation.")
    print("To execute the issue implementation entry flow, use the skill directly:")
    print(f"  /yoke advance {item}")
    print()
    print("It creates or re-enters the item's implementation worktree.")


def route_polish(identity: CodexIdentity, args: list[str]) -> None:
    """Route /yoke polish command."""
    if not args:
        print(
            "yoke-entry: usage: python3 -m runtime.harness.codex.codex_entry polish YOK-N", file=sys.stderr
        )
        sys.exit(1)
    print(_identity_block(identity))
    item = " ".join(args)
    print()
    print("This wrapper displays guidance only — it does not claim the item or")
    print("update status. To execute the full polish flow (claim, status")
    print("transition, review, and verification), use the skill directly:")
    print(f"  /yoke polish {item}")
    print()
    print("Polish is a standalone operator entrypoint. It uses the item's")
    print("recorded worktree rather than the /yoke do session-offer loop.")


def route_usher(identity: CodexIdentity, args: list[str]) -> None:
    """Route /yoke usher command."""
    if not args:
        print(
            "yoke-entry: usage: python3 -m runtime.harness.codex.codex_entry usher YOK-N [--dry-run]",
            file=sys.stderr,
        )
        sys.exit(1)
    print(_identity_block(identity))
    item = " ".join(args)
    print()
    print("This wrapper displays guidance only -- it does not claim the item,")
    print("merge branches, update status, or run deployment. To execute the")
    print("top-level usher flow, use the skill directly:")
    print(f"  /yoke usher {item}")
    print()
    print("Usher is a standalone operator entrypoint. For first-time Codex")
    print("validation, run it with --dry-run before allowing merge/deploy.")


def show_help(identity: CodexIdentity) -> None:
    """Show available commands."""
    print("python3 -m runtime.harness.codex.codex_entry -- Codex harness entry launcher")
    print()
    print("Commands:")
    print("  bootstrap   Load Yoke startup context (orientation)")
    print("  env         Print sourceable exports for shell-managed wrappers")
    print("  idea TITLE  File a new backlog item via /yoke idea")
    print("  do          Start autonomous session via /yoke do")
    print("  refine YOK-N  Critique and improve item artifacts via /yoke refine")
    print("  advance YOK-N implementation  Open issue implementation via /yoke advance")
    print("  polish YOK-N  Review and finish implementation via /yoke polish")
    print("  usher YOK-N [--dry-run]  Merge/deploy handoff via /yoke usher")
    print("  help        Show this help")
    print()
    print(f"Environment:")
    print(f"  YOKE_EXECUTOR={identity.executor}")
    print(f"  YOKE_PROVIDER={identity.provider}")
    print(f"  YOKE_MODEL={identity.display_model()}")
    print(f"  YOKE_ROOT={identity.root}")
    print("  (YOKE_SUPPORTED_PATHS removed — capabilities derived server-side)")
    print()
    print("This is a wrapper-only launcher. It emits the identity")
    print("contract that Codex should carry into subsequent")
    print("operator commands. Use 'env' if you need sourceable")
    print("exports in a shell-managed wrapper. Hook-enhanced mode")
    print("is optional and provided by a separate hook pack.")
    print()
    print(f"Supported entrypoints: {identity.entrypoints()}")
    print(f"Downstream paths: {identity.downstream_paths()}")
    print()
    print("See docs/harness-bootstrap.md for the full contract.")


def main() -> None:
    """CLI entry point."""
    root = resolve_root()
    identity = CodexIdentity(root)

    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    rest = sys.argv[2:]

    if cmd == "bootstrap":
        do_bootstrap(identity)
    elif cmd == "env":
        show_env(identity)
    elif cmd == "idea":
        route_idea(identity, rest)
    elif cmd == "do":
        route_do(identity)
    elif cmd == "refine":
        route_refine(identity, rest)
    elif cmd == "advance":
        route_advance(identity, rest)
    elif cmd == "polish":
        route_polish(identity, rest)
    elif cmd == "usher":
        route_usher(identity, rest)
    elif cmd in ("help", "--help", "-h"):
        show_help(identity)
    else:
        print(
            f"yoke-entry: unknown command: {cmd} (use 'help' for available commands)",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
