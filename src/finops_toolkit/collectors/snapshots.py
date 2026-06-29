"""Orphaned EBS snapshots: self-owned snapshots whose source volume no longer exists.
Read-only: describe_snapshots + describe_volumes. Savings are ranged in Phase 2 because
incremental snapshots free far less than nominal size."""

from __future__ import annotations

import boto3

from ..schema import Confidence, Detection, Effort, Risk


def collect(session: boto3.Session, region: str, account_id: str) -> list[Detection]:
    ec2 = session.client("ec2", region_name=region)

    existing_volumes = {
        v["VolumeId"]
        for page in ec2.get_paginator("describe_volumes").paginate()
        for v in page["Volumes"]
    }

    out: list[Detection] = []
    for page in ec2.get_paginator("describe_snapshots").paginate(OwnerIds=["self"]):
        for snap in page["Snapshots"]:
            src = snap.get("VolumeId")
            if not src or src in existing_volumes:
                continue
            sid = snap["SnapshotId"]
            size = snap.get("VolumeSize", 0)
            out.append(
                Detection(
                    id=f"snapshot-orphaned-{sid}",
                    check="snapshot-orphaned",
                    service="ec2",
                    category="storage",
                    title=f"Orphaned EBS snapshot (source volume gone, {size} GB nominal)",
                    resource_id=sid,
                    resource_arn=f"arn:aws:ec2:{region}:{account_id}:snapshot/{sid}",
                    region=region,
                    evidence=f"Snapshot's source volume {src} no longer exists.",
                    effort=Effort.low,
                    risk=Risk.caution,
                    confidence=Confidence.medium,
                    confidence_reason="Detection is deterministic; saving is ranged because "
                    "incremental snapshots free less than nominal size.",
                    caveats=["Estimate is ranged: incremental snapshots free far less than nominal size."],
                    pricing={"size_gb": size},
                )
            )
    return out
