"""EBS checks: unattached volumes, gp2->gp3 opportunities, volumes on stopped instances.
Read-only: describe_volumes + describe_instances only."""

from __future__ import annotations

import boto3

from ..schema import Confidence, Detection, Effort, Risk


def _arn(region: str, account_id: str, vol_id: str) -> str:
    return f"arn:aws:ec2:{region}:{account_id}:volume/{vol_id}"


def collect(session: boto3.Session, region: str, account_id: str) -> list[Detection]:
    ec2 = session.client("ec2", region_name=region)
    detections: list[Detection] = []

    stopped: dict[str, str] = {}  # instance_id -> state
    for page in ec2.get_paginator("describe_instances").paginate():
        for res in page["Reservations"]:
            for inst in res["Instances"]:
                stopped[inst["InstanceId"]] = inst["State"]["Name"]

    for page in ec2.get_paginator("describe_volumes").paginate():
        for vol in page["Volumes"]:
            vid = vol["VolumeId"]
            size = vol["Size"]
            vtype = vol["VolumeType"]
            pricing = {"size_gb": size, "volume_type": vtype}
            arn = _arn(region, account_id, vid)

            if vol["State"] == "available":
                detections.append(
                    Detection(
                        id=f"ebs-unattached-{vid}",
                        check="ebs-unattached",
                        service="ec2",
                        category="storage",
                        title=f"Unattached {vtype} EBS volume ({size} GB)",
                        resource_id=vid,
                        resource_arn=arn,
                        region=region,
                        evidence=f"Volume is in 'available' state, attached to no instance.",
                        effort=Effort.trivial,
                        risk=Risk.caution,
                        confidence=Confidence.high,
                        confidence_reason="Detached state is deterministic; EBS storage is not "
                        "SP/RI-covered, so list price is exact.",
                        caveats=["Snapshot before deletion unless covered by a backup process."],
                        pricing=pricing,
                    )
                )
                continue

            attachment = (vol.get("Attachments") or [{}])[0]
            inst_id = attachment.get("InstanceId")
            if inst_id and stopped.get(inst_id) == "stopped":
                detections.append(
                    Detection(
                        id=f"ebs-on-stopped-{vid}",
                        check="ebs-on-stopped-instance",
                        service="ec2",
                        category="storage",
                        title=f"EBS volume on stopped instance ({size} GB)",
                        resource_id=vid,
                        resource_arn=arn,
                        region=region,
                        evidence=f"Volume attached to {inst_id}, which is stopped; storage still billed.",
                        effort=Effort.low,
                        risk=Risk.caution,
                        confidence=Confidence.high,
                        confidence_reason="Stopped-instance storage is billed while compute is not.",
                        caveats=["Confirm the instance is not awaiting a planned restart."],
                        pricing=pricing,
                    )
                )

            if vtype == "gp2":
                detections.append(
                    Detection(
                        id=f"ebs-gp2-gp3-{vid}",
                        check="ebs-gp2-to-gp3",
                        service="ec2",
                        category="storage",
                        title=f"gp2 volume migratable to gp3 ({size} GB)",
                        resource_id=vid,
                        resource_arn=arn,
                        region=region,
                        evidence=f"{size} GB gp2 volume; gp3 baseline is cheaper per GB.",
                        effort=Effort.trivial,
                        risk=Risk.safe,
                        confidence=Confidence.high,
                        confidence_reason="gp2->gp3 is a live, zero-downtime modify; storage delta "
                        "is deterministic.",
                        auto_applyable=True,
                        pricing=pricing,
                    )
                )

    return detections
