"""Architecture exemption vocabulary shared by pure validators and storage."""

ARCHITECTURE_EXEMPTION_FAMILIES = frozenset(
    {
        'architecture_generated',
        'architecture_fixture',
        'architecture_archive',
        'architecture_test_surface',
        'architecture_pack_source',
    }
)
