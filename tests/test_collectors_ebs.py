import boto3
import pytest
from moto import mock_aws

from finops_toolkit.collectors import ebs

REGION = "eu-west-1"
AMI = "ami-12345678"


@pytest.fixture
def session():
    with mock_aws():
        yield boto3.Session(region_name=REGION)


def _run_instance(ec2, state_stopped: bool) -> str:
    iid = ec2.run_instances(ImageId=AMI, MinCount=1, MaxCount=1, InstanceType="t3.micro")[
        "Instances"
    ][0]["InstanceId"]
    if state_stopped:
        ec2.stop_instances(InstanceIds=[iid])
    return iid


def test_ebs_collector_detects_three_check_types(session):
    ec2 = session.client("ec2", region_name=REGION)
    stopped = _run_instance(ec2, state_stopped=True)
    running = _run_instance(ec2, state_stopped=False)

    # unattached gp2 -> unattached (skips gp2->gp3 because it's available, not in-use)
    v_unattached = ec2.create_volume(AvailabilityZone=f"{REGION}a", Size=500, VolumeType="gp2")["VolumeId"]
    # gp2 attached to stopped instance -> on-stopped + gp2->gp3
    v_stopped = ec2.create_volume(AvailabilityZone=f"{REGION}a", Size=100, VolumeType="gp2")["VolumeId"]
    ec2.attach_volume(VolumeId=v_stopped, InstanceId=stopped, Device="/dev/sdf")
    # gp2 attached to running instance -> gp2->gp3 only
    v_running = ec2.create_volume(AvailabilityZone=f"{REGION}a", Size=200, VolumeType="gp2")["VolumeId"]
    ec2.attach_volume(VolumeId=v_running, InstanceId=running, Device="/dev/sdg")

    dets = ebs.collect(session, REGION, "111122223333")
    ids_by_check: dict[str, set[str]] = {}
    for d in dets:
        ids_by_check.setdefault(d.check, set()).add(d.resource_id)

    # membership-based: moto auto-creates root volumes, so don't assert exact totals
    assert v_unattached in ids_by_check["ebs-unattached"]
    assert v_running not in ids_by_check.get("ebs-unattached", set())
    assert v_stopped in ids_by_check["ebs-on-stopped-instance"]
    assert {v_stopped, v_running} <= ids_by_check["ebs-gp2-to-gp3"]
    # the unattached volume is a delete candidate, never a migrate candidate
    assert v_unattached not in ids_by_check["ebs-gp2-to-gp3"]

    unattached = next(d for d in dets if d.resource_id == v_unattached)
    assert unattached.pricing == {"size_gb": 500, "volume_type": "gp2"}
    assert all(d.resource_arn and d.confidence_reason for d in dets)


def test_ebs_collector_empty_account(session):
    assert ebs.collect(session, REGION, "111122223333") == []
