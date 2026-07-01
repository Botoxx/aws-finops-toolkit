"""EC2 rightsizing (check 11): we surface AWS Compute Optimizer's own recommendations rather
than judging utilization ourselves ('AWS says downsize' is defensible; 'my script decided your
prod box is idle' is not). Each recommendation carries an estimated monthly saving in currency.

Degrades gracefully: if Compute Optimizer is not opted in, emit one advisory finding telling the
customer to enable it — never error, never fabricate.

Read-only: compute-optimizer:GetEC2InstanceRecommendations."""

from __future__ import annotations

import boto3

from ..schema import Confidence, Detection, Effort, Risk

_ACTIONABLE = {"OVER_PROVISIONED", "UNDER_PROVISIONED", "NOT_OPTIMIZED"}


def _not_enabled(region: str, account_id: str) -> Detection:
    """The Compute Optimizer call failed (not opted in / no permission) — a coverage gap."""
    return Detection(
        id="rightsizing-enable-compute-optimizer",
        check="rightsizing",
        service="compute-optimizer",
        category="compute",
        title="Compute Optimizer not enabled — rightsizing analysis unavailable",
        resource_id=f"account-{account_id}",
        region=region,
        evidence="AWS Compute Optimizer could not be queried (not opted in, still warming up, or "
        "no compute-optimizer: permission); rightsizing was NOT assessed.",
        effort=Effort.trivial,
        risk=Risk.safe,
        confidence=Confidence.low,
        confidence_reason="No recommendations available; this is guidance, not a quantified saving.",
        caveats=["Enable Compute Optimizer (free) and re-run after ~24h for rightsizing savings."],
        pricing={"monthly_savings_eur": 0.0},
    )


def _no_actionable(region: str, account_id: str) -> Detection:
    """Compute Optimizer IS enabled and returned no actionable rightsizing — a clean result, not a
    gap. Kept distinct from _not_enabled so we never tell a customer to enable a service already on."""
    return Detection(
        id="rightsizing-none-actionable",
        check="rightsizing",
        service="compute-optimizer",
        category="compute",
        title="No rightsizing opportunities from Compute Optimizer",
        resource_id=f"account-{account_id}",
        region=region,
        evidence="Compute Optimizer is enabled and found no actionable rightsizing recommendations.",
        effort=Effort.trivial,
        risk=Risk.safe,
        confidence=Confidence.low,
        confidence_reason="Informational: AWS assessed the fleet and flagged nothing actionable.",
        caveats=["No action needed now; re-run periodically as usage patterns change."],
        pricing={"monthly_savings_eur": 0.0},
    )


def _best_saving(rec: dict) -> float:
    best = 0.0
    for opt in rec.get("recommendationOptions", []):
        val = opt.get("savingsOpportunity", {}).get("estimatedMonthlySavings", {}).get("value", 0)
        best = max(best, float(val or 0))
    return best


def collect(session: boto3.Session, region: str, account_id: str) -> list[Detection]:
    co = session.client("compute-optimizer", region_name=region)
    try:
        resp = co.get_ec2_instance_recommendations()
    except Exception:
        return [_not_enabled(region, account_id)]

    recs = resp.get("instanceRecommendations", [])
    if not recs:
        return [_not_enabled(region, account_id)]

    out: list[Detection] = []
    for rec in recs:
        if rec.get("finding") not in _ACTIONABLE:
            continue
        save = _best_saving(rec)
        if save <= 0:
            continue
        arn = rec.get("instanceArn", "")
        inst_id = arn.rsplit("/", 1)[-1] or rec.get("instanceName", "instance")
        out.append(
            Detection(
                id=f"rightsizing-{inst_id}",
                check="rightsizing",
                service="ec2",
                category="compute",
                title=f"Rightsizing opportunity ({rec.get('finding', '').lower()})",
                resource_id=inst_id,
                resource_arn=arn or None,
                region=region,
                evidence=f"Compute Optimizer finds instance {inst_id} {rec.get('finding', '').lower()}.",
                effort=Effort.low,
                risk=Risk.caution,
                confidence=Confidence.high,
                confidence_reason="Recommendation and saving are AWS Compute Optimizer's own.",
                caveats=["Validate the target type against peak load before resizing."],
                pricing={"monthly_savings_eur": round(save, 2)},
            )
        )
    return out or [_no_actionable(region, account_id)]
