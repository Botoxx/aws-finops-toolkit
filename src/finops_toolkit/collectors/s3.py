"""S3 incomplete multipart uploads: parts that were never completed or aborted keep
billing as storage. The fix is an abort-incomplete-multipart-upload lifecycle rule.
Read-only: list_buckets + get_bucket_location + list_multipart_uploads."""

from __future__ import annotations

import boto3

from ..schema import Confidence, Detection, Effort, Risk


def _bucket_region(s3, bucket: str) -> str:
    loc = s3.get_bucket_location(Bucket=bucket).get("LocationConstraint")
    return loc or "us-east-1"  # us-east-1 reports None


def collect(session: boto3.Session, region: str, account_id: str) -> list[Detection]:
    s3 = session.client("s3", region_name=region)
    out: list[Detection] = []

    for b in s3.list_buckets().get("Buckets", []):
        bucket = b["Name"]
        try:
            bregion = _bucket_region(s3, bucket)
        except Exception:
            continue
        regional = session.client("s3", region_name=bregion)
        uploads = regional.list_multipart_uploads(Bucket=bucket).get("Uploads", [])
        if not uploads:
            continue
        out.append(
            Detection(
                id=f"s3-incomplete-mpu-{bucket}",
                check="s3-incomplete-mpu",
                service="s3",
                category="storage",
                title=f"S3 bucket with {len(uploads)} incomplete multipart upload(s)",
                resource_id=bucket,
                resource_arn=f"arn:aws:s3:::{bucket}",
                region=bregion,
                evidence=f"{len(uploads)} incomplete multipart upload(s) still billed as storage.",
                effort=Effort.trivial,
                risk=Risk.safe,
                confidence=Confidence.medium,
                confidence_reason="Presence is deterministic; size needs list-parts, so saving is "
                "a conservative floor.",
                auto_applyable=True,
                caveats=["Add an abort-incomplete-multipart-upload lifecycle rule to prevent recurrence."],
                pricing={"upload_count": len(uploads)},
            )
        )
    return out
