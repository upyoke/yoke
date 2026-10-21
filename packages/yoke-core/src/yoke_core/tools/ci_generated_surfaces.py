"""Read-only CI contracts for canonical generated teaching surfaces."""

from __future__ import annotations

from pathlib import Path


def check_generated_blocks(repo_root: Path, _scope: object) -> tuple[bool, str]:
    from yoke_core.tools.generated_block_render import check_families

    rc, summary = check_families(repo_root)
    return rc == 0, summary.strip() or "generated blocks match canonical sources"


def check_harness_capability(repo_root: Path, _scope: object) -> tuple[bool, str]:
    from yoke_core.tools import harness_continuation_coherence as coherence
    from yoke_core.tools import render_harness_capability_inline as renderer

    result = renderer.render(repo_root, check=True)
    claims = renderer.uncited_capability_claims(repo_root)
    continuations = coherence.continuation_contract_contradictions(repo_root)
    detail = "".join((
        renderer.format_render_drift(result, check=True),
        renderer.format_uncited_summary(claims),
        coherence.format_continuation_summary(continuations),
    )).strip()
    ok = result.ok and not result.changed and not claims and not continuations
    return ok, detail or "wake teaching matches harness capability contracts"


def check_agent_render(repo_root: Path, _scope: object) -> tuple[bool, str]:
    from yoke_core.domain.agents_render import detect_substrate_drift

    drift = detect_substrate_drift(target_root=repo_root)
    if not drift:
        return True, "rendered harness adapters match canonical sources"
    return False, (
        "agent-render drift:\n" + "\n".join(drift)
        + "\nRun `yoke agents render`, commit the outputs and rerun CI."
    )
