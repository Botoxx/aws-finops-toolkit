"""Orchestrate the read-only collectors into a prioritized findings[] list.
Ordering is deterministic code (the Prioritization Model), not an LLM decision: safe,
high-confidence quick wins first to build trust, then the larger/riskier levers by value."""

from __future__ import annotations

import boto3

from . import savings
from .collectors import amis, commitment, ebs, networking, rightsizing, s3, snapshots
from .schema import Confidence, Detection, Effort, Finding, Risk

# regional collectors run once per region; global ones run once for the account
_REGIONAL = (ebs.collect, networking.collect, snapshots.collect, amis.collect, rightsizing.collect)
_GLOBAL = (s3.collect, commitment.collect)

_EFFORT_RANK = {Effort.trivial: 0, Effort.low: 1, Effort.medium: 2, Effort.high: 3}


def _is_quick_win(f: Finding) -> bool:
    return f.risk == Risk.safe and _EFFORT_RANK[f.effort] <= 1 and f.confidence == Confidence.high


def prioritize(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda f: (0 if _is_quick_win(f) else 1, -f.monthly_savings_eur))


def account_id(session: boto3.Session) -> str:
    return session.client("sts", region_name="us-east-1").get_caller_identity()["Account"]


def collect_detections(session: boto3.Session, regions: list[str], acct: str) -> list[Detection]:
    dets: list[Detection] = []
    for region in regions:
        for fn in _REGIONAL:
            dets.extend(fn(session, region, acct))
    primary = regions[0] if regions else "us-east-1"
    for fn in _GLOBAL:
        dets.extend(fn(session, primary, acct))
    return dets


def audit(session: boto3.Session, regions: list[str], acct: str | None = None) -> list[Finding]:
    acct = acct or account_id(session)
    detections = collect_detections(session, regions, acct)
    return prioritize(savings.price_all(detections))
