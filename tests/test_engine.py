import boto3
import pytest
from moto import mock_aws

from finops_toolkit import engine

REGION = "eu-west-1"


@pytest.fixture
def session():
    with mock_aws():
        yield boto3.Session(region_name=REGION)


def test_audit_prices_and_prioritizes(session):
    ec2 = session.client("ec2", region_name=REGION)
    iid = ec2.run_instances(ImageId="ami-base", MinCount=1, MaxCount=1)["Instances"][0]["InstanceId"]
    # gp2 attached to a running instance -> gp2->gp3 (safe/trivial/high = quick win)
    v = ec2.create_volume(AvailabilityZone=f"{REGION}a", Size=200, VolumeType="gp2")["VolumeId"]
    ec2.attach_volume(VolumeId=v, InstanceId=iid, Device="/dev/sdf")
    # unattached volume -> caution (not a quick win)
    ec2.create_volume(AvailabilityZone=f"{REGION}a", Size=500, VolumeType="gp2")

    findings = engine.audit(session, [REGION])

    assert findings, "expected findings"
    # every finding is priced and ranked
    assert all(f.monthly_savings_eur >= 0 for f in findings)
    # quick wins (safe/trivial/high) sort ahead of caution findings
    gp3_idx = next(i for i, f in enumerate(findings) if f.check == "ebs-gp2-to-gp3")
    unattached_idx = next(i for i, f in enumerate(findings) if f.check == "ebs-unattached")
    assert gp3_idx < unattached_idx

    # CE / Compute Optimizer unavailable under moto -> graceful, not a crash
    # (commitment yields nothing; rightsizing yields an advisory)
    checks = {f.check for f in findings}
    assert "rightsizing" in checks
