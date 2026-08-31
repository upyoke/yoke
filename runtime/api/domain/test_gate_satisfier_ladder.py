"""The satisfier-ladder mechanism: rung ordering, refusals, and remedies.

These exercise the mechanism itself against a hand-built fact registry,
so a failure here is about the ladder rather than about any one gate.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.gate_satisfier_facts import (
    CapabilityFacts,
    Fact,
    FactVerdict,
)
from yoke_core.domain.gate_satisfier_ladder import (
    LadderUnsatisfied,
    SatisfierLadder,
    SatisfierRung,
    render_refusal,
    require_rung,
    resolve_ladder,
)


LADDER = SatisfierLadder(
    obligation="proof_of_landing",
    statement="The work must be shown to have landed somewhere.",
    rungs=(
        SatisfierRung(
            rung_id="strongest",
            summary="a remote verified it",
            requires=("declared:capability:remote_check", "observed:remote_ok"),
            declared_by_capability="remote_check",
        ),
        SatisfierRung(
            rung_id="weaker",
            summary="the local tree shows it",
            requires=("observed:local_ok",),
        ),
    ),
    remedy="produce one of the two proofs above.",
)


def _facts(**verdicts: FactVerdict) -> CapabilityFacts:
    return CapabilityFacts(
        facts={
            key.replace("__", ":"): Fact(
                key=key.replace("__", ":"), verdict=verdict, detail="fixture"
            )
            for key, verdict in verdicts.items()
        }
    )


def test_highest_reachable_rung_wins():
    facts = _facts(
        **{
            "declared__capability__remote_check": FactVerdict.PRESENT,
            "observed__remote_ok": FactVerdict.PRESENT,
            "observed__local_ok": FactVerdict.PRESENT,
        }
    )
    assert resolve_ladder(LADDER, facts).rung_id == "strongest"


def test_falls_to_the_lower_rung_when_the_higher_one_is_unreachable():
    facts = _facts(
        **{
            "observed__remote_ok": FactVerdict.ABSENT,
            "observed__local_ok": FactVerdict.PRESENT,
        }
    )
    resolution = resolve_ladder(LADDER, facts)
    assert resolution.rung_id == "weaker"
    assert [r.rung_id for r in resolution.rejected] == ["strongest"]


def test_no_reachable_rung_is_unsatisfied_rather_than_a_pass():
    facts = _facts(**{"observed__local_ok": FactVerdict.ABSENT})
    resolution = resolve_ladder(LADDER, facts)
    assert resolution.satisfied is False
    assert resolution.rung is None


def test_unknown_fact_is_not_treated_as_absent_or_as_present():
    facts = CapabilityFacts(facts={})
    resolution = resolve_ladder(LADDER, facts)
    assert resolution.satisfied is False
    verdicts = {r.verdict for r in resolution.rejected}
    assert verdicts == {"unknown"}


def test_require_rung_raises_with_the_full_narrative():
    facts = _facts(**{"observed__local_ok": FactVerdict.ABSENT})
    with pytest.raises(LadderUnsatisfied) as excinfo:
        require_rung(LADDER, facts)
    message = excinfo.value.message
    assert "proof_of_landing" in message
    assert "strongest" in message and "weaker" in message
    assert "produce one of the two proofs above." in message


def test_refusal_names_capability_undeclaration_as_a_remedy():
    facts = _facts(**{"observed__local_ok": FactVerdict.ABSENT})
    message = render_refusal(LADDER, resolve_ladder(LADDER, facts))
    assert "remote_check" in message
    assert "undeclare" in message
    assert "capability-settings remove" in message
    assert "never make it silently" in message


def test_refusal_reports_the_specific_missing_fact_per_rung():
    facts = _facts(
        **{
            "declared__capability__remote_check": FactVerdict.PRESENT,
            "observed__remote_ok": FactVerdict.ABSENT,
            "observed__local_ok": FactVerdict.ABSENT,
        }
    )
    resolution = resolve_ladder(LADDER, facts)
    missing = {r.rung_id: r.missing_fact for r in resolution.rejected}
    assert missing == {
        "strongest": "observed:remote_ok",
        "weaker": "observed:local_ok",
    }


def test_resolution_carries_the_fact_snapshot_for_stamping():
    facts = _facts(**{"observed__local_ok": FactVerdict.PRESENT})
    resolution = resolve_ladder(LADDER, facts)
    assert resolution.facts == {"observed:local_ok": "present"}


def test_a_derived_fact_no_observer_owns_names_the_engine_defect():
    """A derived fact is only unknown when nothing can answer it.

    Convergence has a live-observation fallback, so an absent row is
    not unknown; a key no observer owns is, and no sync fixes that.
    """
    facts = CapabilityFacts(facts={})
    assert "engine defect" in facts.explain("derived:remote_present")


def test_with_observed_layers_site_facts_over_the_registry():
    facts = CapabilityFacts(facts={}).with_observed(
        {"observed:local_ok": (True, "the local tree has it")}
    )
    assert facts.present("observed:local_ok")
    assert facts.explain("observed:local_ok") == "the local tree has it"
