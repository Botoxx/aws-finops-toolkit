"""CloudWatch helper for idle-detection collectors. Isolated so idle logic is unit-testable
by stubbing this one function."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import boto3


def metric_sum(
    session: boto3.Session,
    region: str,
    namespace: str,
    metric_name: str,
    dimensions: list[dict],
    days: int = 30,
    period: int = 86400,
) -> float:
    """Total of a metric over the trailing `days`. Returns 0.0 when CloudWatch reports no datapoints.
    A failed query (throttle / AccessDenied) raises and is surfaced as a collector gap upstream, so a
    successful empty result means 'no activity' — e.g. ALB RequestCount emits nothing on zero
    requests, which is exactly the idle signal we want to flag."""
    cw = session.client("cloudwatch", region_name=region)
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    resp = cw.get_metric_statistics(
        Namespace=namespace,
        MetricName=metric_name,
        Dimensions=dimensions,
        StartTime=start,
        EndTime=end,
        Period=period,
        Statistics=["Sum"],
    )
    return sum(p["Sum"] for p in resp.get("Datapoints", []))
