import pytest
from pydantic import ValidationError

from finops_toolkit.schema import Finding


def _f(**kw) -> Finding:
    base = dict(
        id="x", check="c", service="ec2", category="storage", title="t",
        resource_id="r", region="eu-west-1", evidence="e", monthly_savings_eur=100.0,
        effort="trivial", risk="safe", confidence="high", confidence_reason="c",
    )
    base.update(kw)
    return Finding(**base)


def test_bounds_rejects_monthly_above_high():
    with pytest.raises(ValidationError):
        _f(monthly_savings_eur=400.0, savings_low_eur=300.0, savings_high_eur=380.0)


def test_bounds_rejects_monthly_below_low():
    with pytest.raises(ValidationError):
        _f(monthly_savings_eur=100.0, savings_low_eur=300.0, savings_high_eur=480.0)


def test_bounds_rejects_unpaired_bound():
    with pytest.raises(ValidationError):
        _f(savings_low_eur=300.0, savings_high_eur=None)


def test_bounds_accepts_ordered_range():
    f = _f(monthly_savings_eur=400.0, savings_low_eur=300.0, savings_high_eur=480.0)
    assert (f.savings_low_eur, f.monthly_savings_eur, f.savings_high_eur) == (300.0, 400.0, 480.0)


def test_bounds_revalidated_on_assignment():
    # validate_assignment=True must re-run _bounds so the invariant can't be broken post-construction
    f = _f(monthly_savings_eur=400.0, savings_low_eur=300.0, savings_high_eur=480.0)
    with pytest.raises(ValidationError):
        f.monthly_savings_eur = 9999.0
