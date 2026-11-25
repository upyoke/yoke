"""Supply real bundle citations in review fixtures."""


def cite_case(bundle, rationale):
    (case,) = bundle["cases"]
    artifacts = case["artifacts"]
    if artifacts:
        return f"{rationale} See artifact {artifacts[0]['id']}."
    return f"{rationale} See run {case['capture_run_id']}."
