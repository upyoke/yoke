"""Pack manifests couple shipped payloads to catalog and executable contracts."""

PACK_PREFIX_CONTRACTS = (
    (
        "pack_catalog_contract",
        ("packs/", "packages/yoke-core/src/yoke_core/install_bundle_tree/packs/"),
        (
            "runtime/api/domain/test_pack_catalog.py",
            "runtime/api/domain/test_pack_prerequisite_catalog.py",
        ),
    ),
    (
        "structured_events_pack_contract",
        (
            "packs/structured-events/",
            "packages/yoke-core/src/yoke_core/install_bundle_tree/packs/structured-events/",
        ),
        ("runtime/api/domain/test_structured_events_pack.py",),
    ),
)
