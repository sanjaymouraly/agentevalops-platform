import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from app.analytics import _binom_two_sided, paired_agent_comparison


class T:
    def __init__(self, agent, bench, rep, passed): self.agent_id, self.benchmark_id, self.repetition, self.passed, self.status = agent, bench, rep, passed, "completed"

def test_mcnemar_identical_agents_not_significant():
    trials = [T(1, 1, r, True) for r in (1,2,3)] + [T(2, 1, r, True) for r in (1,2,3)]
    r = paired_agent_comparison(trials, 1, 2)
    assert r["paired_trials"] == 3 and r["mcnemar_exact_p"] == 1.0 and not r["significant_at_0_05"]

def test_mcnemar_strong_difference_significant():
    # A passes 10 paired trials that B fails (10 discordant, all one direction) -> p ~ 0.002
    trials = [T(1, 1, r, True) for r in range(1, 11)] + [T(2, 1, r, False) for r in range(1, 11)]
    r = paired_agent_comparison(trials, 1, 2)
    assert r["a_only_pass"] == 10 and r["mcnemar_exact_p"] < 0.05 and r["significant_at_0_05"]
    assert _binom_two_sided(0, 10) < 0.01
