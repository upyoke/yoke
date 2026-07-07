"""Current Codex custom-subagent schema assertions for the rendered adapters.

Sibling of ``test_agents_render_substrate.py`` (which is at the line cap).
Covers the schema-truth ACs for YOK-1887: every generated
``runtime/harness/codex/agents/yoke-*.toml`` parses with ``tomllib``,
carries the required ``name`` / ``description`` / ``developer_instructions``
keys, omits the retired ``prompt`` / ``tools`` / ``max_turns`` / stale-model
fields, and expresses role posture via the documented ``sandbox_mode``
field. The renderer's model-policy knob (omit-by-default, pin-on-opt-in) is
exercised directly so the inheritance default cannot silently regress.
"""

from __future__ import annotations

from pathlib import Path

import pytest

try:
    import tomllib
except ImportError:  # Python < 3.11 fallback
    import tomli as tomllib  # type: ignore

from yoke_core.domain.agents_render import AGENTS, CANONICAL_DIR, CODEX_OUT_DIR
from yoke_core.domain.agents_render_codex import (
    load_codex_spec,
    render_codex_agent,
)

# Codex documents these as the only legal sandbox postures.
_ALLOWED_SANDBOX = {"read-only", "workspace-write", "danger-full-access"}

# AC-6 / AC-16 posture: only the engineer carries a write-capable sandbox;
# every read-only Yoke role stays read-only.
_EXPECTED_SANDBOX = {
    "product-manager": "read-only",
    "product-designer": "read-only",
    "architect": "read-only",
    "tester": "read-only",
    "simulator": "read-only",
    "boss": "read-only",
    "engineer": "workspace-write",
}

# Retired adapter keys that must never reappear in a generated Codex TOML.
_FORBIDDEN_KEYS = ("prompt", "tools", "max_turns")

# Claude model nicknames carry no Codex meaning (stale cross-provider pin).
_CLAUDE_MODEL_NICKNAMES = {"opus", "sonnet", "haiku"}


def _repo_root() -> Path:
    # runtime/api/domain/<thisfile> → parents[3] is the checkout root.
    return Path(__file__).resolve().parents[3]


def _generated_toml(role: str) -> dict:
    out = _repo_root() / CODEX_OUT_DIR / f"yoke-{role}.toml"
    assert out.exists(), f"missing generated Codex adapter for {role}: {out}"
    return tomllib.loads(out.read_text(encoding="utf-8"))


@pytest.mark.parametrize("role", AGENTS)
def test_generated_toml_parses_and_has_required_keys(role: str) -> None:
    """AC-1 / AC-8: each rendered adapter parses and carries the required keys."""
    data = _generated_toml(role)
    assert data.get("name") == f"yoke-{role}", (
        f"{role}: name mismatch, got {data.get('name')!r}"
    )
    assert isinstance(data.get("description"), str) and data["description"], (
        f"{role}: missing or empty description"
    )
    body = data.get("developer_instructions")
    assert isinstance(body, str) and len(body) > 100, (
        f"{role}: missing or suspiciously short developer_instructions"
    )


@pytest.mark.parametrize("role", AGENTS)
def test_generated_toml_omits_retired_fields(role: str) -> None:
    """AC-1/2/3/15: no legacy prompt / tools / max_turns key survives."""
    data = _generated_toml(role)
    present = [key for key in _FORBIDDEN_KEYS if key in data]
    assert not present, f"{role}: retired Codex adapter keys present: {present}"


@pytest.mark.parametrize("role", AGENTS)
def test_generated_toml_has_no_stale_model_pin(role: str) -> None:
    """AC-4/5: model is omitted by default (inherit); never a Claude nickname."""
    data = _generated_toml(role)
    model = data.get("model")
    # No role pins a model today, so the field must be absent (inheritance).
    assert model is None, (
        f"{role}: unexpected model pin {model!r} — default posture omits model"
    )


@pytest.mark.parametrize("role", AGENTS)
def test_generated_toml_sandbox_posture(role: str) -> None:
    """AC-6/16: sandbox_mode posture is explicit, legal, and role-correct."""
    data = _generated_toml(role)
    sandbox = data.get("sandbox_mode")
    assert sandbox in _ALLOWED_SANDBOX, (
        f"{role}: sandbox_mode {sandbox!r} not in {_ALLOWED_SANDBOX}"
    )
    assert sandbox == _EXPECTED_SANDBOX[role], (
        f"{role}: expected sandbox_mode {_EXPECTED_SANDBOX[role]!r}, got {sandbox!r}"
    )


@pytest.mark.parametrize("role", AGENTS)
def test_sidecar_sandbox_value_is_legal(role: str) -> None:
    """AC-6: each Codex sidecar declares a documented sandbox posture."""
    spec = load_codex_spec(_repo_root() / CANONICAL_DIR, role)
    assert spec.get("sandbox_mode") in _ALLOWED_SANDBOX, (
        f"{role}.codex.json sandbox_mode {spec.get('sandbox_mode')!r} is not legal"
    )
    # Sidecars must not carry the retired adapter keys either.
    leftovers = [key for key in (*_FORBIDDEN_KEYS, "model") if key in spec]
    assert not leftovers, f"{role}.codex.json carries retired keys: {leftovers}"


@pytest.mark.parametrize("role", AGENTS)
def test_developer_instructions_preserve_canonical_body(role: str) -> None:
    """AC-7/8: the canonical body's lead prose flows into developer_instructions
    (single-source body — no second canonical Codex prompt)."""
    data = _generated_toml(role)
    canonical_md = (_repo_root() / CANONICAL_DIR / f"{role}.md").read_text("utf-8")
    lead = next(
        (
            line.strip()
            for line in canonical_md.splitlines()
            if line.strip() and not line.lstrip().startswith("<!--")
        ),
        "",
    )
    assert lead and lead in data["developer_instructions"], (
        f"{role}: canonical lead line {lead!r} not found in developer_instructions"
    )


def _write_minimal_canonical(tmp_path: Path, role: str, sidecar: str) -> Path:
    canonical = tmp_path / CANONICAL_DIR
    canonical.mkdir(parents=True, exist_ok=True)
    (canonical / f"{role}.md").write_text(
        f"You are the {role}. " + ("Body padding. " * 20) + "\n",
        encoding="utf-8",
    )
    (canonical / f"{role}.codex.json").write_text(sidecar, encoding="utf-8")
    return canonical


def test_model_policy_pinned_emits_model(tmp_path: Path) -> None:
    """AC-5: an explicit pinned policy emits the named model verbatim."""
    canonical = _write_minimal_canonical(
        tmp_path, "architect",
        '{"name": "yoke-architect", "description": "x", '
        '"model_policy": "pinned", "model": "gpt-fixed-1"}',
    )
    rendered = render_codex_agent(canonical, "architect")
    header = rendered.split('developer_instructions = """', 1)[0]
    assert 'model = "gpt-fixed-1"' in header, (
        f"pinned model not emitted; header was:\n{header}"
    )


@pytest.mark.parametrize(
    "sidecar",
    [
        '{"name": "yoke-architect", "description": "x"}',
        '{"name": "yoke-architect", "description": "x", "model_policy": "inherit", "model": "gpt-x"}',
        '{"name": "yoke-architect", "description": "x", "model_policy": "latest"}',
    ],
)
def test_model_policy_default_omits_model(tmp_path: Path, sidecar: str) -> None:
    """AC-5: absent / inherit / latest policy omits model so Codex inherits."""
    canonical = _write_minimal_canonical(tmp_path, "architect", sidecar)
    rendered = render_codex_agent(canonical, "architect")
    header = rendered.split('developer_instructions = """', 1)[0]
    assert "model = " not in header, (
        f"model unexpectedly emitted for non-pinned policy; header was:\n{header}"
    )
