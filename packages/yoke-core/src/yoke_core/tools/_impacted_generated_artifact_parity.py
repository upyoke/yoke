"""Always-run floor: repo-global generated-artifact parity and drift.

WHY: Atlas integrity, rendered agent adapters, and the install-bundle
snapshot have no import edge to the files that can break them. Lanes run
impacted selection, so this family must execute on every local impacted
run. Keep the set fast (roughly 30 seconds).
"""

GENERATED_ARTIFACT_PARITY_TESTS = (
    "runtime/api/engines/test_doctor_hc_atlas.py",
    "runtime/api/engines/test_doctor_tier_discipline_live_repo.py",
    "runtime/api/domain/test_path_context.py",
    "runtime/api/cli/test_yoke_product_boundary_github_actions_wait_run.py",
    "runtime/api/domain/test_agents_render.py",
    "runtime/api/test_harness_cli_manifest.py",
    "runtime/api/engines/test_doctor_agent_drift.py",
    "runtime/api/domain/test_install_bundle.py",
    "runtime/api/domain/test_install_bundle_tree_sync.py",
    "runtime/api/engines/test_doctor_hc_install_bundle_drift.py",
)

__all__ = ["GENERATED_ARTIFACT_PARITY_TESTS"]
