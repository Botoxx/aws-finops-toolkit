"""Commitment coverage gap (check 10): the largest single lever. We don't estimate the
discount ourselves — we read Cost Explorer's own Savings Plans purchase recommendation, which
returns an estimated monthly saving in currency. Recommend-only.

Read-only: ce:GetSavingsPlansPurchaseRecommendation. CE is a global service (us-east-1)."""

from __future__ import annotations

import boto3

from ..schema import Category, Confidence, Detection, Effort, Risk


def _unavailable(account_id: str, err: Exception) -> Detection:
    """CE could not be queried (often missing ce: permissions). Surface a gap, not silence —
    a hidden commitment lever is the single largest saving we could be failing to report."""
    return Detection(
        id="commitment-coverage-unknown",
        check="collector-error",
        service="ce",
        category=Category.commitment,
        title="Savings Plans recommendation unavailable",
        resource_id=f"account-{account_id}",
        region="global",
        evidence=f"Cost Explorer SP recommendation could not be retrieved ({type(err).__name__}); "
        "commitment coverage was NOT assessed (check ce: permissions).",
        effort=Effort.trivial,
        risk=Risk.safe,
        confidence=Confidence.low,
        confidence_reason="CE query error — a coverage gap, not a finding.",
        pricing={"monthly_savings_eur": 0.0},
    )


def collect(session: boto3.Session, region: str, account_id: str) -> list[Detection]:
    ce = session.client("ce", region_name="us-east-1")
    try:
        resp = ce.get_savings_plans_purchase_recommendation(
            SavingsPlansType="COMPUTE_SP",
            TermInYears="ONE_YEAR",
            PaymentOption="NO_UPFRONT",
            LookbackPeriodInDays="THIRTY_DAYS",
        )
    except Exception as e:
        return [_unavailable(account_id, e)]

    summary = resp.get("SavingsPlansPurchaseRecommendation", {}).get(
        "SavingsPlansPurchaseRecommendationSummary", {}
    )
    est = float(summary.get("EstimatedMonthlySavingsAmount") or 0)
    if est <= 0:
        return []

    pct = summary.get("EstimatedSavingsPercentage")
    cov_note = f" CE estimates ~{pct}% saving vs current on-demand compute." if pct else ""
    return [
        Detection(
            id="commitment-coverage-gap",
            check="commitment-coverage-gap",
            service="ce",
            category="commitment",
            title="Low Savings Plans coverage on steady-state compute",
            resource_id=f"account-{account_id}",
            region="global",
            evidence=f"AWS recommends a 1-year no-upfront Compute Savings Plan.{cov_note}",
            effort=Effort.medium,
            risk=Risk.safe,
            confidence=Confidence.high,
            confidence_reason="Cost Explorer's own purchase-recommendation estimate; the bounds are a "
            "heuristic band (-10% / +30%) around that single point estimate, not a tier comparison.",
            caveats=["Assumes steady-state usage continues; commit only to the durable baseline."],
            pricing={
                "monthly_savings_eur": round(est, 2),
                "savings_low_eur": round(est * 0.9, 2),
                "savings_high_eur": round(est * 1.3, 2),
            },
        )
    ]
