"""Check that live registry entries have explicit teaching homes."""


def check_registry_coverage(model, live):
    """Direct concept references cover entries; parent references never do."""
    for kind in ("commands", "functions", "skills"):
        mapped = {
            value
            for concept in model.concepts.values()
            for value in concept.get(kind, [])
        }
        for missing in sorted(set(live[kind]) - mapped):
            model.problem(
                "UNMAPPED_REGISTRY_ENTRY",
                "docs/teaching/model/concepts",
                f"{kind} entry {missing!r} has no direct concept mapping; "
                f"add it to the appropriate concept's {kind} list, then rebuild",
            )
