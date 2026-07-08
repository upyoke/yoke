from __future__ import annotations

from pathlib import Path


def test_deploy_bridge_dispatch_ref_tracks_product_branch_without_override():
    workflow = (
        Path(__file__).resolve().parents[3]
        / ".github/workflows/yoke-deploy-bridge.yml"
    )
    text = workflow.read_text(encoding="utf-8")

    assert "DISPATCH_REF_OVERRIDE: ${{ vars.YOKE_DEPLOY_DISPATCH_REF }}" in text
    assert 'dispatch_ref="$DISPATCH_REF_OVERRIDE"' in text
    assert 'dispatch_ref="$PRODUCT_BRANCH"' in text
    assert text.count('--ref "$dispatch_ref"') == 2
    assert '--ref "$DISPATCH_REF"' not in text
