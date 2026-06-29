"""Savings math: turn Detections into priced Findings. Every euro figure in the product
originates in this module (and in the CE/Compute-Optimizer collectors, which already return
currency). The LLM never computes any of it."""

from __future__ import annotations

from . import pricing
from .schema import Detection, Finding


def _r(x: float) -> float:
    return round(x, 2)


def price_detection(d: Detection) -> Finding:
    p = d.pricing
    check = d.check
    monthly: float
    low: float | None = None
    high: float | None = None
    extra_caveat: str | None = pricing.LIST_PRICE_CAVEAT

    if check in ("ebs-unattached", "ebs-on-stopped-instance"):
        monthly = p["size_gb"] * pricing.ebs_gb_month(p["volume_type"])
    elif check == "ebs-gp2-to-gp3":
        delta = pricing.EBS_GB_MONTH["gp2"] - pricing.EBS_GB_MONTH["gp3"]
        monthly = p["size_gb"] * delta
    elif check in ("snapshot-orphaned", "ami-unused"):
        nominal = p["size_gb"] * pricing.SNAPSHOT_GB_MONTH
        low = nominal * pricing.SNAPSHOT_INCREMENTAL_LOW
        high = nominal * pricing.SNAPSHOT_INCREMENTAL_HIGH
        monthly = (low + high) / 2
    elif check == "eip-unassociated":
        monthly = p["hours"] * pricing.EIP_IDLE_HOUR
    elif check == "nat-idle":
        monthly = p["hours"] * pricing.NAT_GATEWAY_HOUR
    elif check == "elb-idle":
        rate = pricing.NLB_HOUR if p.get("lb_type") == "network" else pricing.ALB_HOUR
        monthly = p["hours"] * rate
    elif check == "s3-incomplete-mpu":
        monthly = 0.0  # size needs list-parts; report as a hygiene fix, not a quantified saving
        extra_caveat = "Saving not quantified (incomplete-upload size unknown); value is recurrence prevention."
    elif "monthly_savings_eur" in p:
        # commitment-coverage / rightsizing: AWS (CE / Compute Optimizer) already computed currency
        monthly = p["monthly_savings_eur"]
        low = p.get("savings_low_eur")
        high = p.get("savings_high_eur")
        extra_caveat = None
    else:
        raise ValueError(f"no savings formula for check {check!r}")

    finding = d.priced(
        _r(monthly),
        _r(low) if low is not None else None,
        _r(high) if high is not None else None,
    )
    if extra_caveat and extra_caveat not in finding.caveats:
        finding.caveats.append(extra_caveat)
    return finding


def price_all(detections: list[Detection]) -> list[Finding]:
    return [price_detection(d) for d in detections]
