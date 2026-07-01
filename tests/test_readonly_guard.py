"""The read-only guarantee, enforced at runtime: a botocore before-call hook records every
AWS operation a full collector sweep issues, and asserts each is a describe/get/list verb.
If a collector ever issues a mutating call, this test fails before the IAM policy would even
get a chance to deny it."""

import boto3
import pytest
from moto import mock_aws

from finops_toolkit.collectors import amis, commitment, ebs, networking, rightsizing, s3, snapshots

REGION = "eu-west-1"
READONLY_PREFIXES = ("Describe", "Get", "List", "BatchGet")


@pytest.fixture
def session():
    with mock_aws():
        yield boto3.Session(region_name=REGION)


def test_collectors_issue_only_readonly_calls(session, monkeypatch):
    ec2 = session.client("ec2", region_name=REGION)
    # seed a representative resource set (these create calls are made BEFORE the recorder)
    iid = ec2.run_instances(ImageId="ami-base", MinCount=1, MaxCount=1)["Instances"][0]["InstanceId"]
    ec2.stop_instances(InstanceIds=[iid])
    ec2.create_volume(AvailabilityZone=f"{REGION}a", Size=10, VolumeType="gp2")
    ec2.allocate_address(Domain="vpc")
    ec2.create_image(InstanceId=iid, Name="img-1")
    s3c = session.client("s3", region_name=REGION)
    s3c.create_bucket(Bucket="bucket-one", CreateBucketConfiguration={"LocationConstraint": REGION})

    monkeypatch.setattr(networking, "metric_sum", lambda *a, **k: 0.0)

    calls: list[str] = []
    session._session.register("before-call", lambda model, **kw: calls.append(model.name))

    acct = "111122223333"
    # include commitment + rightsizing: they hit CE / Compute Optimizer (mutating-capable services),
    # so the read-only sweep must cover them too — they degrade to a Get + advisory under moto.
    per_collector: dict[str, int] = {}
    for mod in (ebs, networking, snapshots, amis, s3, commitment, rightsizing):
        before = len(calls)
        mod.collect(session, REGION, acct)
        per_collector[mod.__name__.rsplit(".", 1)[-1]] = len(calls) - before

    assert calls, "expected the collectors to make AWS calls"
    offenders = [c for c in calls if not c.startswith(READONLY_PREFIXES)]
    assert offenders == [], f"non-read-only operations issued: {sorted(set(offenders))}"
    # every collector must actually issue at least one recorded op — a collector that early-returns
    # before calling AWS would contribute nothing and silently read as "safe" in the aggregate.
    silent = [name for name, n in per_collector.items() if n == 0]
    assert silent == [], f"collectors issued no AWS calls (auditing nothing): {silent}"
