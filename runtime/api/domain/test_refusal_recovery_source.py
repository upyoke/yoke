"""All executable Python recovery labels belong to the shared composer."""

from __future__ import annotations

import ast
import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
COMPOSER = "packages/yoke-contracts/src/yoke_contracts/refusal_recovery.py"
# Permanent migration history and standalone versioned Pack programs cannot
# gain a dependency on the current runtime. The browser reply runs JavaScript.
# The standalone relay entrypoint diagnoses failure before packages are bound.
# Freeze these exact source versions: this is no allowance for new literals.
FROZEN_SOURCES = {
    'packages/yoke-core/src/yoke_core/tools/session_relay_runtime_entrypoint.py':
        '354609e83ce5e9d26f5f2a1df29c271f1be3bf702528d3418a8feab9f1259f9b',
    'packages/yoke-core/src/yoke_core/domain/migrations/0053_retire_advance_skill.py':
        '934f51effddc4856d35d38dd2d606028f08092bf2fe556f1f8f1f2604c8841c4',
    'packages/yoke-core/src/yoke_core/domain/migrations/0054_remove_lane_allowlists.py':
        '8902deadbd0d8306e261e08f23adc1520767503379644a7435c8aaff0d311ab8',
    'packages/yoke-core/src/yoke_core/domain/migrations/0055_remove_process_offer_settings.py':
        '8858eed1aadf5831c0be3f261b3be0c5bf7189364441b074320619b940b51535',
    'packages/yoke-core/src/yoke_core/domain/migrations/0059_rename_session_lanes_to_levels.py':
        '8b1fa302477c697766a3e299ab6055bac0de9c2aa119d70e2be7d9ac915492bd',
    'packages/yoke-core/src/yoke_core/domain/migrations/0061_declare_hosted_runtime_consumer.py':
        '0a4b6854496104e1d1d87fefa7e8b5fc2f116fea0157ae8a32fa4b9190d9d48c',
    'packages/yoke-core/src/yoke_core/domain/migrations/0062_one_org_role_per_person.py':
        '3d4edecfbda6a7d4d9d1c5aedda42888ea3b862c15bb3a0392407d780557dac4',
    'packages/yoke-core/src/yoke_core/domain/migrations/0063_converge_levels_to_universe.py':
        '79c29f330b210bbd032400afaf8c7e9d053b455498a7c812c8219b9983e91f32',
    'packages/yoke-core/src/yoke_core/domain/migrations/0065_remove_fleet_settings.py':
        '68cbfcc015841ed2c9cfe9d2a4d2b4cc897b3dca1e061609f53af9e822d13e1b',
    'packages/yoke-core/src/yoke_core/domain/migrations/0069_retire_operator_session_mode.py':
        'a16dfab7a292d574bfc589df1adb5359b02407704e03b97eafe134dd1809b344',
    'packages/yoke-core/src/yoke_core/domain/migrations/0070_native_domain_instants.py':
        'de06ed9551c557eaa3229bf1ab2ac3ab9f6279ae02dc683a3b643bc74d9f6551',
    'packages/yoke-core/src/yoke_core/domain/migrations/0071_model_effort_levels.py':
        '04489df9f8bdfdaee5dac04823352c0331ab07ce8afe7b0096e6146ce6b16933',
    'packages/yoke-core/src/yoke_core/domain/migrations/0072_retire_core_system_actor.py':
        '4210acc0ae70cef13fbde60b2ae8eb6fd315d930e07e1d74507bba72a05207d0',
    'packages/yoke-core/src/yoke_core/domain/migrations/0081_project_optional_sessions.py':
        '164e934a314b703fbe2fd7597b81eb83d9d04f5f14de8c5d1a76f503918d96f5',
    'packages/yoke-core/src/yoke_core/domain/migrations/0084_task_files_touched_from_body.py':
        'b02393a93803350b6b520477f20f88c4efaf185607a124abf8df1b6485e18fda',
    'packages/yoke-core/src/yoke_core/domain/migrations/0090_qa_test_machine_keys.py':
        '6cb294c3c600a2ae720866c46319e9015394422e8f06fd34b98e928fed7381b6',
    'packages/yoke-core/src/yoke_core/domain/migrations/_native_instant_document_fields.py':
        '6611e9fc229a5326b60276f615b7030cd63d42ab93aab91ff8f892d6cc10f096',
    'packages/yoke-core/src/yoke_core/domain/migrations/_native_instant_documents.py':
        '19dc26f22a66c7922c498ce253de80371b2036d92790ad792425f7d4571cf140',
    'packages/yoke-core/src/yoke_core/domain/migrations/_native_instant_storage.py':
        'f9f4febf1d186cde733a9a6bfb19dc19ab4c06d0f81ed202edd43d3f6607818f',
    'packages/yoke-core/src/yoke_core/domain/migrations/_native_relay_instant_documents.py':
        'ea4baa3fc6f2a5ae4979d562fa46904a62786b84450881f09d8a43badbc18053',
    'packages/yoke-core/src/yoke_core/install_bundle_tree/packs/ephemeral-environments/versions/1.2.0/files/ops/frozen_preview_occupancy.py':
        '5ca48ff54ebe3c219e430dbe21a0fa2f74321ca7c528e5f8a3775c97257dc367',
    'packages/yoke-core/src/yoke_core/install_bundle_tree/packs/ephemeral-environments/versions/1.3.0/files/ops/frozen_preview_occupancy.py':
        'c2c6f630541a3a34e9c4c826fbf03e1716a5b26e9085c872b1c02991e4fb3a05',
    'packages/yoke-core/src/yoke_core/ui/static/universe_views_levels.js':
        '88c59ea4e62abcaadeb03fa61e0c38441c367a3c2bd4807024db23f699ede3d7',
}


def test_no_hand_written_recovery_labels() -> None:
    paths = subprocess.check_output(
        ["git", "-C", str(ROOT), "ls-files", "--", "packages", "runtime"],
        text=True,
    ).splitlines()
    violations = []
    for rel in paths:
        p = ROOT / rel
        if (
            p.suffix not in {".py", ".js"}
            or p.name.startswith("test_")
            or "/tests/" in rel
            or rel == COMPOSER
        ):
            continue
        source = p.read_text()
        if "Recovery:" not in source:
            continue
        if p.suffix == ".py" and not any(
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "Recovery:" in node.value
            for node in ast.walk(ast.parse(source))
        ):
            continue
        if hashlib.sha256(p.read_bytes()).hexdigest() == FROZEN_SOURCES.get(rel):
            continue
        violations.append(rel)
    assert not violations, (
        "Compose refusals with yoke_contracts.refusal_recovery.compose_refusal: "
        + ", ".join(violations)
    )
