"""Hidden verifier tests. Never copied into the agent-visible workspace."""
import calc


def test_add():
    assert calc.add(2, 3) == 5
    assert calc.add(-1, 1) == 0


def test_average():
    assert calc.average([1, 2, 3]) == 2
    assert calc.average([]) == 0


def test_apply_discount():
    assert abs(calc.apply_discount(100, 10) - 90) < 1e-9
    assert abs(calc.apply_discount(50, 0) - 50) < 1e-9


def test_clamp():
    assert calc.clamp(5, 1, 3) == 3
    assert calc.clamp(-5, 1, 3) == 1
    assert calc.clamp(2, 1, 3) == 2
