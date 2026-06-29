"""Orchestrate the read-only collectors into a prioritized findings[] list.
Ordering is deterministic code (the Prioritization Model), not an LLM decision: safe,
high-confidence quick wins first to build trust, then the larger/riskier levers by value."""

from __future__ import annotations

import boto3

from . import savings
from .collectors import amis, commitment, ebs, networking, rightsizing, s3, snapshots
from .schema import Category, Confidence, Detection, Effort, Finding, Risk

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


def _gap(area: str, region: str, acct: str, err: Exception) -> Detection:
    """A collector failed. Emit it as a visible coverage gap, never silence: in a cost audit,
    'we could not look' must not read as 'nothing here'."""
    return Detection(
        id=f"collector-error-{area}-{region}",
        check="collector-error",
        service=area,
        category=Category.other,
        title=f"Could not complete {area} checks in {region}",
        resource_id=f"account-{acct}",
        region=region,
        evidence=f"The {area} collector failed ({type(err).__name__}); this area was NOT assessed.",
        effort=Effort.trivial,
        risk=Risk.safe,
        confidence=Confidence.low,
        confidence_reason="Collector error — a coverage gap, not a finding. Resolve and re-run.",
        pricing={"monthly_savings_eur": 0.0},
    )


def _safe_collect(fn, session: boto3.Session, region: str, acct: str) -> list[Detection]:
    try:
        return list(fn(session, region, acct))
    except Exception as e:  # one collector/region failing must not abort the whole audit
        return [_gap(fn.__module__.rsplit(".", 1)[-1], region, acct, e)]


def collect_detections(session: boto3.Session, regions: list[str], acct: str) -> list[Detection]:
    dets: list[Detection] = []
    for region in regions:
        for fn in _REGIONAL:
            dets.extend(_safe_collect(fn, session, region, acct))
    primary = regions[0] if regions else "us-east-1"
    for fn in _GLOBAL:
        dets.extend(_safe_collect(fn, session, primary, acct))
    return dets


def audit(session: boto3.Session, regions: list[str], acct: str | None = None) -> list[Finding]:
    acct = acct or account_id(session)
    detections = collect_detections(session, regions, acct)
    return prioritize(savings.price_all(detections))
