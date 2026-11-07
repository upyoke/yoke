"""Pack manifests couple shipped payloads to catalog and executable contracts."""

PACK_PREFIX_CONTRACTS = (
    (
        "pack_catalog_contract",
        ("packs/",),
        (
            "runtime/api/domain/test_pack_catalog.py",
            "runtime/api/domain/test_pack_prerequisite_catalog.py",
        ),
    ),
    (
        "structured_events_pack_contract",
        (
            "events/",
            "packs/structured-events/",
        ),
        ("runtime/api/domain/test_structured_events_pack.py",),
    ),
)
