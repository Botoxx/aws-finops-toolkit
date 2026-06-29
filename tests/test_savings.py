import pytest

from finops_toolkit import pricing, savings
from finops_toolkit.schema import Confidence, Detection, Effort, Risk


def _det(check: str, pricing_inputs: dict, **kw) -> Detection:
    base = dict(
        id=f"{check}-x",
        check=check,
        service="ec2",
        category="storage",
        title="t",
        resource_id="r",
        region="eu-west-1",
        evidence="e",
        effort=Effort.trivial,
        risk=Risk.safe,
        confidence=Confidence.high,
        confidence_reason="c",
        pricing=pricing_inputs,
    )
    base.update(kw)
    return Detection(**base)


def test_ebs_unattached_uses_list_price_per_type():
    f = savings.price_detection(_det("ebs-unattached", {"size_gb": 500, "volume_type": "gp2"}))
    assert f.monthly_savings_eur == round(500 * pricing.EBS_GB_MONTH["gp2"], 2)  # 58.0
    assert pricing.LIST_PRICE_CAVEAT in f.caveats


def test_gp2_to_gp3_prices_only_the_delta():
    f = savings.price_detection(_det("ebs-gp2-to-gp3", {"size_gb": 500, "volume_type": "gp2"}))
    assert f.monthly_savings_eur == 11.6


def test_snapshot_savings_are_ranged_and_conservative():
    f = savings.price_detection(_det("snapshot-orphaned", {"size_gb": 100}))
    nominal = 100 * pricing.SNAPSHOT_GB_MONTH  # 5.0
    assert f.savings_low_eur == 1.5
    assert f.savings_high_eur == 5.0
    # headline never exceeds nominal — we never sum nominal sizes as the saving
    assert f.monthly_savings_eur <= nominal
    assert f.savings_low_eur <= f.monthly_savings_eur <= f.savings_high_eur


def test_flat_rate_charges():
    eip = savings.price_detection(_det("eip-unassociated", {"hours": 730}, category="networking"))
    nat = savings.price_detection(_det("nat-idle", {"hours": 730}, category="networking"))
    alb = savings.price_detection(
        _det("elb-idle", {"hours": 730, "lb_type": "application"}, category="networking")
    )
    assert eip.monthly_savings_eur == 3.65
    assert nat.monthly_savings_eur == 35.04
    assert alb.monthly_savings_eur == 18.4


def test_s3_mpu_is_unquantified_hygiene_fix():
    f = savings.price_detection(_det("s3-incomplete-mpu", {"upload_count": 3}))
    assert f.monthly_savings_eur == 0.0
    assert any("recurrence" in c for c in f.caveats)
    assert pricing.LIST_PRICE_CAVEAT not in f.caveats  # no list price involved


def test_aws_sourced_savings_pass_through_without_list_caveat():
    f = savings.price_detection(
        _det(
            "commitment-coverage-gap",
            {"monthly_savings_eur": 410.0, "savings_low_eur": 300.0, "savings_high_eur": 480.0},
            category="commitment",
        )
    )
    assert (f.monthly_savings_eur, f.savings_low_eur, f.savings_high_eur) == (410.0, 300.0, 480.0)
    assert pricing.LIST_PRICE_CAVEAT not in f.caveats
