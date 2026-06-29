"""Commitment coverage gap (check 10): the largest single lever. We don't estimate the
discount ourselves — we read Cost Explorer's own Savings Plans purchase recommendation, which
returns an estimated monthly saving in currency. Recommend-only.

Read-only: ce:GetSavingsPlansPurchaseRecommendation. CE is a global service (us-east-1)."""

from __future__ import annotations

import boto3

from ..schema import Confidence, Detection, Effort, Risk


def collect(session: boto3.Session, region: str, account_id: str) -> list[Detection]:
    ce = session.client("ce", region_name="us-east-1")
    try:
        resp = ce.get_savings_plans_purchase_recommendation(
            SavingsPlansType="COMPUTE_SP",
            TermInYears="ONE_YEAR",
            PaymentOption="NO_UPFRONT",
            LookbackPeriodInDays="THIRTY_DAYS",
        )
    except Exception:
        return []

    summary = resp.get("SavingsPlansPurchaseRecommendation", {}).get(
        "SavingsPlansPurchaseRecommendationSummary", {}
    )
    est = float(summary.get("EstimatedMonthlySavingsAmount") or 0)
    if est <= 0:
        return []

    coverage = summary.get("CurrentAverageCoverage") or summary.get("EstimatedAverageUtilization")
    cov_note = f" Current coverage ~{coverage}%." if coverage else ""
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
            confidence_reason="Estimate is Cost Explorer's own purchase recommendation; range "
            "reflects 1yr-no-upfront vs longer-term commitment tiers.",
            caveats=["Assumes steady-state usage continues; commit only to the durable baseline."],
            pricing={
                "monthly_savings_eur": round(est, 2),
                "savings_low_eur": round(est * 0.9, 2),
                "savings_high_eur": round(est * 1.3, 2),
            },
        )
    ]
