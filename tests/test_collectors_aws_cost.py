"""Stubber tests for the CE / Compute Optimizer collectors (moto's support is thin here).
Verifies we read AWS's own currency estimates and degrade gracefully."""

import boto3
import pytest
from botocore.stub import Stubber

from finops_toolkit.collectors import commitment, rightsizing


class _FakeSession:
    """Returns a pre-stubbed client regardless of the requested service/region."""

    def __init__(self, client):
        self._client = client

    def client(self, *a, **k):
        return self._client


def _client(service, region="us-east-1"):
    return boto3.client(
        service, region_name=region, aws_access_key_id="x", aws_secret_access_key="x"
    )


def test_commitment_reads_ce_estimated_saving():
    ce = _client("ce")
    stub = Stubber(ce)
    stub.add_response(
        "get_savings_plans_purchase_recommendation",
        {
            "SavingsPlansPurchaseRecommendation": {
                "SavingsPlansPurchaseRecommendationSummary": {
                    "EstimatedMonthlySavingsAmount": "410.0"
                }
            }
        },
    )
    stub.activate()
    dets = commitment.collect(_FakeSession(ce), "eu-west-1", "111122223333")
    assert len(dets) == 1
    d = dets[0]
    assert d.check == "commitment-coverage-gap"
    assert d.pricing["monthly_savings_eur"] == 410.0
    assert d.pricing["savings_low_eur"] <= 410.0 <= d.pricing["savings_high_eur"]


def test_commitment_silent_when_no_recommendation():
    ce = _client("ce")
    stub = Stubber(ce)
    stub.add_response(
        "get_savings_plans_purchase_recommendation",
        {
            "SavingsPlansPurchaseRecommendation": {
                "SavingsPlansPurchaseRecommendationSummary": {
                    "EstimatedMonthlySavingsAmount": "0.0"
                }
            }
        },
    )
    stub.activate()
    assert commitment.collect(_FakeSession(ce), "eu-west-1", "111122223333") == []


def test_commitment_gap_when_summary_absent():
    # CE returns 200 but no usable summary (insufficient lookback / warming up). That is a coverage
    # gap, NOT a confirmed zero — it must surface, not collapse to "coverage already optimal".
    ce = _client("ce")
    stub = Stubber(ce)
    stub.add_response("get_savings_plans_purchase_recommendation", {"SavingsPlansPurchaseRecommendation": {}})
    stub.activate()
    dets = commitment.collect(_FakeSession(ce), "eu-west-1", "111122223333")
    assert len(dets) == 1
    assert dets[0].check == "collector-error"
    assert dets[0].confidence.value == "low"


def test_commitment_gap_when_estimate_is_empty_string():
    # CE frequently returns the summary present with an empty-string amount ("" not "0") for the
    # warming-up / nothing-eligible case — that must be a gap, not collapse to a confirmed zero.
    ce = _client("ce")
    stub = Stubber(ce)
    stub.add_response(
        "get_savings_plans_purchase_recommendation",
        {
            "SavingsPlansPurchaseRecommendation": {
                "SavingsPlansPurchaseRecommendationSummary": {"EstimatedMonthlySavingsAmount": ""}
            }
        },
    )
    stub.activate()
    dets = commitment.collect(_FakeSession(ce), "eu-west-1", "111122223333")
    assert len(dets) == 1
    assert dets[0].check == "collector-error"


def test_commitment_advisory_on_ce_error():
    # CE permission/throttle error must surface as a visible gap, not vanish as "no opportunity"
    ce = _client("ce")
    stub = Stubber(ce)
    stub.add_client_error("get_savings_plans_purchase_recommendation", "AccessDeniedException")
    stub.activate()
    dets = commitment.collect(_FakeSession(ce), "eu-west-1", "111122223333")
    assert len(dets) == 1
    assert dets[0].check == "collector-error"
    assert dets[0].pricing["monthly_savings_eur"] == 0.0
    assert dets[0].confidence.value == "low"


def test_rightsizing_reads_compute_optimizer_saving():
    co = _client("compute-optimizer", region="eu-west-1")
    stub = Stubber(co)
    stub.add_response(
        "get_ec2_instance_recommendations",
        {
            "instanceRecommendations": [
                {
                    "instanceArn": "arn:aws:ec2:eu-west-1:111122223333:instance/i-0abc",
                    "finding": "OVER_PROVISIONED",
                    "recommendationOptions": [
                        {"savingsOpportunity": {"estimatedMonthlySavings": {"value": 42.5}}}
                    ],
                }
            ]
        },
    )
    stub.activate()
    dets = rightsizing.collect(_FakeSession(co), "eu-west-1", "111122223333")
    over = [d for d in dets if d.resource_id == "i-0abc"]
    assert len(over) == 1
    assert over[0].pricing["monthly_savings_eur"] == 42.5
    assert over[0].confidence.value == "high"


def test_rightsizing_advisory_when_not_opted_in():
    co = _client("compute-optimizer", region="eu-west-1")
    stub = Stubber(co)
    stub.add_response("get_ec2_instance_recommendations", {"instanceRecommendations": []})
    stub.activate()
    dets = rightsizing.collect(_FakeSession(co), "eu-west-1", "111122223333")
    assert len(dets) == 1
    assert dets[0].id == "rightsizing-enable-compute-optimizer"
    assert dets[0].pricing["monthly_savings_eur"] == 0.0
    assert dets[0].confidence.value == "low"


def test_rightsizing_distinguishes_enabled_but_no_actionable():
    # Compute Optimizer IS enabled and returned a non-actionable finding — a clean result, so we
    # must not tell the customer to enable a service that is already on.
    co = _client("compute-optimizer", region="eu-west-1")
    stub = Stubber(co)
    stub.add_response(
        "get_ec2_instance_recommendations",
        {
            "instanceRecommendations": [
                {
                    "instanceArn": "arn:aws:ec2:eu-west-1:111122223333:instance/i-0clean",
                    "finding": "OPTIMIZED",
                    "recommendationOptions": [
                        {"savingsOpportunity": {"estimatedMonthlySavings": {"value": 0.0}}}
                    ],
                }
            ]
        },
    )
    stub.activate()
    dets = rightsizing.collect(_FakeSession(co), "eu-west-1", "111122223333")
    assert len(dets) == 1
    assert dets[0].id == "rightsizing-none-actionable"
    assert "No rightsizing" in dets[0].title
