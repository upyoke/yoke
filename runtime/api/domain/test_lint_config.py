"""Tests for the hook-guard mode registry (``lint_config``).

Pins two invariants: the catalog enumerates every PreToolUse:Bash denier (so a
new chain guard cannot ship without an operator knob), and ``.yoke/lint-config``
lists every cataloged guard. Plus the resolver semantics — default deny, warn,
the protected-guard clamp, and the ``# allow-warn`` override token.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_contracts.hook_runner.chain_registry import chain_for
from yoke_core.domain import lint_config

_REPO_ROOT = Path(__file__).resolve().parents[3]

# Chain members that are not deniers (liveness + observation) and therefore
# carry no enforcement-mode knob.
_NON_DENIERS = frozenset({
    "runtime.harness.hook_helpers_heartbeat",
    "yoke_core.domain.observe_pre",
})


def _write_config(tmp_path: Path, text: str, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "lint-config"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(lint_config, "config_path", lambda root=None: str(path))
    lint_config.reset_cache()


def test_catalog_covers_every_pretooluse_bash_denier() -> None:
    chain = chain_for("PreToolUse", "Bash")
    assert chain, "PreToolUse:Bash chain resolved empty"
    uncatalogued = [
        m for m in chain
        if m not in _NON_DENIERS and not lint_config.is_registered(m)
    ]
    assert not uncatalogued, (
        f"Bash-chain deniers missing from GUARD_CATALOG (add a catalog entry so "
        f"the guard gets an operator knob): {uncatalogued}"
    )


def test_project_lint_config_enumerates_every_catalog_guard() -> None:
    parsed = lint_config._parse(str(_REPO_ROOT / ".yoke" / "lint-config"))
    missing = [g.guard for g in lint_config.GUARD_CATALOG if g.guard not in parsed]
    assert not missing, f".yoke/lint-config is missing entries: {missing}"
    for guard, (mode, _allow) in parsed.items():
        assert mode in (lint_config.DENY, lint_config.WARN), f"{guard}={mode}"


def test_project_lint_config_is_active_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".yoke").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / ".yoke" / "lint-config").write_text(
        "lint_tc_label=warn\n", encoding="utf-8"
    )
    (tmp_path / "data" / "lint-config").write_text(
        "lint_tc_label=deny\n", encoding="utf-8"
    )
    monkeypatch.setattr(lint_config, "_workspace_root", lambda: str(tmp_path))
    lint_config.reset_cache()

    assert lint_config.config_path() == str(tmp_path / ".yoke" / "lint-config")
    assert lint_config.resolve_mode("lint_tc_label") == lint_config.WARN


def test_resolve_mode_explicit_root_ignores_ambient_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ambient = tmp_path / "yoke"
    target = tmp_path / "buzz"
    (ambient / ".yoke").mkdir(parents=True)
    (target / ".yoke").mkdir(parents=True)
    (ambient / ".yoke" / "lint-config").write_text(
        "lint_tc_label=deny\n", encoding="utf-8"
    )
    (target / ".yoke" / "lint-config").write_text(
        "lint_tc_label=warn\n", encoding="utf-8"
    )
    monkeypatch.setattr(lint_config, "_workspace_root", lambda: str(ambient))
    lint_config.reset_cache()

    assert lint_config.resolve_mode("lint_tc_label") == lint_config.DENY
    assert lint_config.resolve_mode("lint_tc_label", root=str(target)) == lint_config.WARN


def test_reset_cache_clears_root_specific_cache(tmp_path: Path) -> None:
    target = tmp_path / "buzz"
    (target / ".yoke").mkdir(parents=True)
    config = target / ".yoke" / "lint-config"
    config.write_text("lint_tc_label=warn\n", encoding="utf-8")
    lint_config.reset_cache()

    assert lint_config.resolve_mode("lint_tc_label", root=str(target)) == lint_config.WARN
    config.write_text("lint_tc_label=deny\n", encoding="utf-8")
    assert lint_config.resolve_mode("lint_tc_label", root=str(target / ".")) == lint_config.WARN
    lint_config.reset_cache()
    assert lint_config.resolve_mode("lint_tc_label", root=str(target)) == lint_config.DENY


def test_default_and_unknown_resolve_to_deny(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_config(tmp_path, "lint_db_cmd=deny\n", monkeypatch)
    assert lint_config.resolve_mode("lint_db_cmd") == lint_config.DENY
    assert lint_config.resolve_mode("yoke_core.domain.lint_db_cmd") == lint_config.DENY
    assert lint_config.resolve_mode("lint_tc_label") == lint_config.DENY  # absent -> default
    assert lint_config.resolve_mode("not_a_real_guard") == lint_config.DENY  # unknown -> fail safe


def test_remote_claude_cli_subguard_resolves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_config(tmp_path, f"{lint_config.REMOTE_CLAUDE_CLI_GUARD}=warn\n", monkeypatch)
    assert lint_config.resolve_mode(lint_config.REMOTE_CLAUDE_CLI_GUARD) == lint_config.WARN


def test_payload_snapshot_overrides_server_local_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, "lint_workspace_cwd_match=deny\n", monkeypatch)
    payload = {
        lint_config.SNAPSHOT_PAYLOAD_KEY: {
            "lint_workspace_cwd_match": {"mode": "warn"},
        },
    }

    assert (
        lint_config.resolve_mode_for_payload("lint_workspace_cwd_match", payload)
        == lint_config.WARN
    )


def test_warn_honored_for_unprotected_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_config(tmp_path, "lint_tc_label=warn\n", monkeypatch)
    assert lint_config.resolve_mode("lint_tc_label") == lint_config.WARN
    # resolvable by full module path too
    assert lint_config.resolve_mode("yoke_core.domain.lint_tc_label") == lint_config.WARN


def test_protected_guard_warn_clamped_without_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_config(tmp_path, "lint_destructive_git=warn\n", monkeypatch)
    assert lint_config.resolve_mode("lint_destructive_git") == lint_config.DENY


def test_protected_guard_warn_allowed_with_override_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_config(tmp_path, f"lint_destructive_git=warn  {lint_config.ALLOW_WARN_TOKEN}\n", monkeypatch)
    assert lint_config.resolve_mode("lint_destructive_git") == lint_config.WARN


def test_render_lists_every_guard_at_deny() -> None:
    text = lint_config.render_lint_config()
    for spec in lint_config.GUARD_CATALOG:
        assert f"{spec.guard}={lint_config.DENY}" in text
        if spec.protected:
            assert lint_config.ALLOW_WARN_TOKEN in text
    assert "Stable telemetry compatibility id: lint-sqlite-cmd" in text
