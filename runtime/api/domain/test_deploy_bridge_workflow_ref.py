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


def test_deploy_bridge_retries_both_workflow_dispatches():
    workflow = (
        Path(__file__).resolve().parents[3]
        / ".github/workflows/yoke-deploy-bridge.yml"
    )
    text = workflow.read_text(encoding="utf-8")

    assert "run_workflow_dispatch() {" in text
    assert "local max_attempts=4" in text
    assert "retrying in ${delay}s" in text
    assert 'run_workflow_dispatch "image build" "$IMAGE_WORKFLOW"' in text
    assert 'run_workflow_dispatch "env deploy" "$DEPLOY_WORKFLOW"' in text
    assert text.count('gh workflow run "$@"') == 1
