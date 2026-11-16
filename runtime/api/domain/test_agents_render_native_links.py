"""Native harness copies remain useful without symlink privileges."""

from pathlib import Path
import shutil

import pytest

from yoke_core.domain import agents_render_native_links as native


@pytest.fixture
def owned(monkeypatch):
    monkeypatch.setattr(native, "assert_target_under_session_work_authority", lambda _path: None)


def test_copy_drift_is_checked_and_refreshed(tmp_path, monkeypatch, owned):
    from yoke_contracts import platform_links

    source = tmp_path / "rendered"
    source.mkdir()
    (source / "agent.md").write_text("first")

    def copy_link(target, path):
        shutil.copytree(target, path)
        return "copy"

    monkeypatch.setattr(platform_links, "link", copy_link)
    args = tmp_path, Path("rendered"), Path(".codex/agents")
    assert native.ensure_native_agents_link(*args, dry_run=False)[0] == "write"
    assert not native.native_agents_link_drift(*args)
    assert native.ensure_native_agents_link(*args, dry_run=False)[0] == "skip"
    (source / "agent.md").write_text("changed")
    assert native.native_agents_link_drift(*args) == ["drift: .codex/agents"]
    assert native.ensure_native_agents_link(*args, dry_run=True)[0] == "would-write"
    assert (tmp_path / ".codex/agents/agent.md").read_text() == "first"
    native.ensure_native_agents_link(*args, dry_run=False)
    assert not native.native_agents_link_drift(*args)
    (tmp_path / ".codex/agents/extra").write_text("stale")
    assert native.native_agents_link_drift(*args)


def test_file_copy_drift(tmp_path, monkeypatch, owned):
    from yoke_contracts import platform_links

    (tmp_path / "hooks.json").write_text("{}")
    monkeypatch.setattr(platform_links, "link", lambda target, path: shutil.copyfile(target, path))
    args = tmp_path, Path("hooks.json"), Path(".codex/hooks.json")
    native.ensure_native_agents_link(*args, dry_run=False)
    assert not native.native_agents_link_drift(*args)
    (tmp_path / ".codex/hooks.json").write_text("changed")
    assert native.native_agents_link_drift(*args)


def test_generated_tree_retains_real_browser_reference():
    root = Path(__file__).resolve().parents[3]
    reference = root / "runtime/harness/claude/agents/references/yoke-tester-browser.md"
    assert reference.is_file() and not reference.is_symlink()
    assert reference.read_bytes() == (root / "runtime/agents/tester-browser.md").read_bytes()


def test_ci_checks_committed_outputs_without_ignored_native_views(tmp_path, monkeypatch):
    from runtime.api.domain.agents_render_substrate_test_support import _seed_minimal_canonical_tree
    from yoke_core.domain import agents_render
    from yoke_core.tools.ci_generated_surfaces import check_agent_render

    _seed_minimal_canonical_tree(tmp_path)
    monkeypatch.setattr(agents_render, "AGENTS", ["architect"])
    for path, content in agents_render._enumerate_outputs(tmp_path):
        destination = tmp_path / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
    assert check_agent_render(tmp_path, None)[0]
    assert "missing: .codex/agents" in agents_render.detect_substrate_drift(target_root=tmp_path)
    (tmp_path / agents_render.CODEX_OUT_DIR / "yoke-architect.toml").write_text("stale")
    assert not check_agent_render(tmp_path, None)[0]
