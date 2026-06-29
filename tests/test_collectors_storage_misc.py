import boto3
import pytest
from moto import mock_aws

from finops_toolkit.collectors import amis, s3, snapshots

REGION = "eu-west-1"


@pytest.fixture
def session():
    with mock_aws():
        yield boto3.Session(region_name=REGION)


def test_orphaned_snapshot_flagged(session):
    ec2 = session.client("ec2", region_name=REGION)
    vol = ec2.create_volume(AvailabilityZone=f"{REGION}a", Size=8, VolumeType="gp2")["VolumeId"]
    snap = ec2.create_snapshot(VolumeId=vol)["SnapshotId"]
    # live snapshot (volume still exists) -> not orphaned
    live = [d for d in snapshots.collect(session, REGION, "111122223333")]
    assert all(d.resource_id != snap for d in live)
    # delete source volume -> snapshot is now orphaned
    ec2.delete_volume(VolumeId=vol)
    dets = snapshots.collect(session, REGION, "111122223333")
    match = [d for d in dets if d.resource_id == snap]
    assert len(match) == 1
    assert match[0].pricing == {"size_gb": 8}
    assert match[0].confidence.value == "medium"


def test_unused_ami_flagged(session):
    ec2 = session.client("ec2", region_name=REGION)
    iid = ec2.run_instances(ImageId="ami-base", MinCount=1, MaxCount=1)["Instances"][0]["InstanceId"]
    ami = ec2.create_image(InstanceId=iid, Name="golden-2023")["ImageId"]
    dets = amis.collect(session, REGION, "111122223333")
    ids = {d.resource_id for d in dets}
    assert ami in ids  # the new image is referenced by no instance


def test_incomplete_mpu_flagged(session):
    s3c = session.client("s3", region_name=REGION)
    bucket = "data-lake-staging"
    s3c.create_bucket(
        Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": REGION}
    )
    s3c.create_multipart_upload(Bucket=bucket, Key="big-object.parquet")
    dets = s3.collect(session, REGION, "111122223333")
    match = [d for d in dets if d.resource_id == bucket]
    assert len(match) == 1
    assert match[0].pricing["upload_count"] == 1
    assert match[0].auto_applyable is True
