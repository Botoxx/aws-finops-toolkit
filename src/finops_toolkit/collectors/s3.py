"""S3 incomplete multipart uploads: parts that were never completed or aborted keep
billing as storage. The fix is an abort-incomplete-multipart-upload lifecycle rule.
Read-only: list_buckets + get_bucket_location + list_multipart_uploads."""

from __future__ import annotations

import boto3

from ..schema import Category, Confidence, Detection, Effort, Risk


def _bucket_region(s3, bucket: str) -> str:
    loc = s3.get_bucket_location(Bucket=bucket).get("LocationConstraint")
    return loc or "us-east-1"  # us-east-1 reports None


def _inaccessible(bucket: str, region: str, err: Exception) -> Detection:
    """A bucket we could not inspect (e.g. GetBucketLocation denied) becomes a visible gap, not a
    silent drop — otherwise a bucket full of MPU waste reads as 'no waste'."""
    return Detection(
        id=f"s3-inaccessible-{bucket}",
        check="collector-error",
        service="s3",
        category=Category.storage,
        title=f"Could not inspect S3 bucket {bucket}",
        resource_id=bucket,
        region=region,
        evidence=f"Bucket access failed ({type(err).__name__}); MPU waste not assessed for it.",
        effort=Effort.trivial,
        risk=Risk.safe,
        confidence=Confidence.low,
        confidence_reason="Bucket access error — a coverage gap, not a finding.",
        pricing={"monthly_savings_eur": 0.0},
    )


def collect(session: boto3.Session, region: str, account_id: str) -> list[Detection]:
    s3 = session.client("s3", region_name=region)
    out: list[Detection] = []

    for b in s3.list_buckets().get("Buckets", []):
        bucket = b["Name"]
        try:
            bregion = _bucket_region(s3, bucket)
            regional = session.client("s3", region_name=bregion)
            uploads = regional.list_multipart_uploads(Bucket=bucket).get("Uploads", [])
        except Exception as e:
            out.append(_inaccessible(bucket, region, e))
            continue
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
