"""Networking checks: unassociated Elastic IPs, idle NAT gateways, idle load balancers.
Read-only: describe_addresses / describe_nat_gateways / describe_load_balancers + CloudWatch."""

from __future__ import annotations

import boto3

from ..schema import Confidence, Detection, Effort, Risk
from .metrics import metric_sum

IDLE_WINDOW_DAYS = 30


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
            traffic = metric_sum(
                session, region, "AWS/NATGateway", "BytesOutToDestination",
                [{"Name": "NatGatewayId", "Value": nat_id}], days=days,
            )
            if traffic is None or traffic > 0:  # None = no data → inconclusive, do not flag idle
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
                    confidence=Confidence.high,
                    confidence_reason=f"No traffic observed over {days} days (standard CloudWatch metric).",
                    caveats=["Confirm no failover/standby role before removal."],
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
            metric = "RequestCount" if lb_type == "application" else "ActiveFlowCount"
            # LoadBalancer dimension value = the trailing app/.. or net/.. portion of the ARN
            dim = arn.split(":loadbalancer/")[-1]
            requests = metric_sum(
                session, region, namespace, metric,
                [{"Name": "LoadBalancer", "Value": dim}], days=days,
            )
            if requests is None or requests > 0:  # None = no data → inconclusive, do not flag idle
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
                    confidence=Confidence.high,
                    confidence_reason=f"Zero {metric} over {days} days (standard CloudWatch metric).",
                    pricing={"hours": 730, "lb_type": lb_type},
                )
            )
    return out


def collect(session: boto3.Session, region: str, account_id: str, days: int = IDLE_WINDOW_DAYS) -> list[Detection]:
    return _eips(session, region) + _nat_gateways(session, region, days) + _load_balancers(session, region, days)
