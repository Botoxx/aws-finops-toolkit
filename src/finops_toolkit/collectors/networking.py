"""Networking checks: unassociated Elastic IPs, idle NAT gateways, idle load balancers.
Read-only: describe_addresses / describe_nat_gateways / describe_load_balancers + CloudWatch."""

from __future__ import annotations

import boto3

from ..schema import Category, Confidence, Detection, Effort, Risk
from .metrics import metric_sum

IDLE_WINDOW_DAYS = 30


def _gap(area: str, resource_id: str, region: str, err: Exception) -> Detection:
    """A networking sub-check (or a single resource's metric query) failed. Emit a visible gap
    rather than letting the exception discard findings already gathered in this region — a
    CloudWatch throttle on one resource must not read as 'no idle networking here'."""
    return Detection(
        id=f"collector-error-networking-{area}-{region}-{resource_id}",
        check="collector-error",
        service="ec2",
        category=Category.networking,
        title=f"Could not fully assess {area} in {region}",
        resource_id=resource_id,
        region=region,
        evidence=f"{area} assessment failed ({type(err).__name__}); this was NOT fully assessed.",
        effort=Effort.trivial,
        risk=Risk.safe,
        confidence=Confidence.low,
        confidence_reason="Coverage gap, not a finding.",
        pricing={"monthly_savings_eur": 0.0},
    )


def _eips(session: boto3.Session, region: str) -> list[Detection]:
    ec2 = session.client("ec2", region_name=region)
    out: list[Detection] = []
    for addr in ec2.describe_addresses().get("Addresses", []):
        if addr.get("AssociationId") or addr.get("InstanceId") or addr.get("NetworkInterfaceId"):
            continue
        alloc = addr.get("AllocationId", addr.get("PublicIp", "eip"))
        out.append(
            Detection(
                id=f"eip-unassociated-{alloc}",
                check="eip-unassociated",
                service="ec2",
                category="networking",
                title="Unassociated Elastic IP",
                resource_id=alloc,
                region=region,
                evidence=f"Elastic IP {addr.get('PublicIp')} is associated with no instance or ENI.",
                effort=Effort.trivial,
                risk=Risk.safe,
                confidence=Confidence.high,
                confidence_reason="Flat hourly charge for an idle public IPv4; state is deterministic.",
                pricing={"hours": 730},
            )
        )
    return out


def _nat_gateways(session: boto3.Session, region: str, days: int) -> list[Detection]:
    ec2 = session.client("ec2", region_name=region)
    out: list[Detection] = []
    for page in ec2.get_paginator("describe_nat_gateways").paginate():
        for nat in page["NatGateways"]:
            if nat.get("State") != "available":
                continue
            nat_id = nat["NatGatewayId"]
            try:
                traffic = metric_sum(
                    session, region, "AWS/NATGateway", "BytesOutToDestination",
                    [{"Name": "NatGatewayId", "Value": nat_id}], days=days,
                )
            except Exception as e:  # a per-resource throttle must not drop the NATs already found
                out.append(_gap("nat-gateway", nat_id, region, e))
                continue
            if traffic > 0:
                continue
            out.append(
                Detection(
                    id=f"nat-idle-{nat_id}",
                    check="nat-idle",
                    service="ec2",
                    category="networking",
                    title="Idle NAT gateway",
                    resource_id=nat_id,
                    region=region,
                    evidence=f"BytesOutToDestination ~0 over {days} days; hourly charge still incurred.",
                    effort=Effort.low,
                    risk=Risk.caution,
                    confidence=Confidence.medium,
                    confidence_reason=f"Zero BytesOutToDestination over {days} days (CloudWatch); medium "
                    f"because a gateway younger than the window, or in a standby/failover role, can read as idle.",
                    caveats=[
                        "Confirm no failover/standby role before removal.",
                        f"A NAT gateway younger than {days} days has little history and may be flagged idle prematurely.",
                    ],
                    pricing={"hours": 730},
                )
            )
    return out


def _load_balancers(session: boto3.Session, region: str, days: int) -> list[Detection]:
    elb = session.client("elbv2", region_name=region)
    out: list[Detection] = []
    for page in elb.get_paginator("describe_load_balancers").paginate():
        for lb in page["LoadBalancers"]:
            if lb.get("State", {}).get("Code") != "active":
                continue
            arn = lb["LoadBalancerArn"]
            lb_type = lb.get("Type", "application")
            namespace = {"application": "AWS/ApplicationELB", "network": "AWS/NetworkELB"}.get(
                lb_type, "AWS/ApplicationELB"
            )
            # ProcessedBytes is a true counter for NLB (ActiveFlowCount is a sampled gauge, invalid
            # to Sum over daily periods); ALB uses RequestCount, which emits nothing at zero requests.
            metric = "RequestCount" if lb_type == "application" else "ProcessedBytes"
            # LoadBalancer dimension value = the trailing app/.. or net/.. portion of the ARN
            dim = arn.split(":loadbalancer/")[-1]
            try:
                requests = metric_sum(
                    session, region, namespace, metric,
                    [{"Name": "LoadBalancer", "Value": dim}], days=days,
                )
            except Exception as e:  # a per-resource throttle must not drop the LBs already found
                out.append(_gap("load-balancer", lb["LoadBalancerName"], region, e))
                continue
            if requests > 0:
                continue
            out.append(
                Detection(
                    id=f"elb-idle-{lb['LoadBalancerName']}",
                    check="elb-idle",
                    service="elasticloadbalancing",
                    category="networking",
                    title=f"Idle {lb_type} load balancer",
                    resource_id=lb["LoadBalancerName"],
                    resource_arn=arn,
                    region=region,
                    evidence=f"No traffic over {days} days; hourly LCU baseline still billed.",
                    effort=Effort.low,
                    risk=Risk.caution,
                    confidence=Confidence.medium,
                    confidence_reason=f"Zero {metric} over {days} days (CloudWatch); medium because a "
                    f"load balancer younger than the window can read as idle.",
                    caveats=[
                        f"A load balancer younger than {days} days may be flagged idle prematurely; "
                        "confirm it is not newly provisioned.",
                    ],
                    pricing={"hours": 730, "lb_type": lb_type},
                )
            )
    return out


def collect(session: boto3.Session, region: str, account_id: str, days: int = IDLE_WINDOW_DAYS) -> list[Detection]:
    # Each sub-check is isolated: a failure in one (e.g. a throttled paginator) emits a gap for
    # that area while the findings from the others are preserved, rather than losing the region.
    out: list[Detection] = []
    for area, fn in (
        ("elastic-ip", lambda: _eips(session, region)),
        ("nat-gateway", lambda: _nat_gateways(session, region, days)),
        ("load-balancer", lambda: _load_balancers(session, region, days)),
    ):
        try:
            out += fn()
        except Exception as e:
            out.append(_gap(area, f"{area}-{region}", region, e))
    return out
