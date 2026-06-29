"""Unused AMIs: self-owned images not referenced by any instance, plus their backing
snapshots. Read-only: describe_images + describe_instances."""

from __future__ import annotations

import boto3

from ..schema import Confidence, Detection, Effort, Risk


def collect(session: boto3.Session, region: str, account_id: str) -> list[Detection]:
    ec2 = session.client("ec2", region_name=region)

    in_use = {
        inst["ImageId"]
        for page in ec2.get_paginator("describe_instances").paginate()
        for res in page["Reservations"]
        for inst in res["Instances"]
    }

    out: list[Detection] = []
    for img in ec2.describe_images(Owners=["self"]).get("Images", []):
        ami = img["ImageId"]
        if ami in in_use:
            continue
        backing_gb = sum(
            bdm["Ebs"]["VolumeSize"]
            for bdm in img.get("BlockDeviceMappings", [])
            if bdm.get("Ebs", {}).get("VolumeSize")
        )
        out.append(
            Detection(
                id=f"ami-unused-{ami}",
                check="ami-unused",
                service="ec2",
                category="storage",
                title=f"Unused AMI ({backing_gb} GB backing snapshots)",
                resource_id=ami,
                resource_arn=f"arn:aws:ec2:{region}:{account_id}:image/{ami}",
                region=region,
                evidence=f"Self-owned AMI '{img.get('Name', ami)}' is used by no running instance.",
                effort=Effort.low,
                risk=Risk.caution,
                confidence=Confidence.high,
                confidence_reason="No instance references this image; backing-snapshot storage is billed.",
                caveats=["Deregistering also requires deleting backing snapshots to realise savings."],
                pricing={"size_gb": backing_gb},
            )
        )
    return out
