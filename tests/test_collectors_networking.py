import boto3
import pytest
from moto import mock_aws

from finops_toolkit.collectors import networking

REGION = "eu-west-1"


@pytest.fixture
def session():
    with mock_aws():
        yield boto3.Session(region_name=REGION)


def test_unassociated_eip_flagged_associated_skipped(session):
    ec2 = session.client("ec2", region_name=REGION)
    idle = ec2.allocate_address(Domain="vpc")["AllocationId"]
    # an associated EIP must not be flagged
    iid = ec2.run_instances(ImageId="ami-123", MinCount=1, MaxCount=1)["Instances"][0]["InstanceId"]
    assoc = ec2.allocate_address(Domain="vpc")["AllocationId"]
    ec2.associate_address(AllocationId=assoc, InstanceId=iid)

    dets = networking.collect(session, REGION, "111122223333")
    eips = [d for d in dets if d.check == "eip-unassociated"]
    ids = {d.resource_id for d in eips}
    assert idle in ids
    assert assoc not in ids


def _make_nat(ec2):
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnet = ec2.create_subnet(VpcId=vpc, CidrBlock="10.0.1.0/24", AvailabilityZone=f"{REGION}a")[
        "Subnet"
    ]["SubnetId"]
    alloc = ec2.allocate_address(Domain="vpc")["AllocationId"]
    return ec2.create_nat_gateway(SubnetId=subnet, AllocationId=alloc)["NatGateway"]["NatGatewayId"]


def test_idle_nat_flagged_when_no_traffic(session, monkeypatch):
    ec2 = session.client("ec2", region_name=REGION)
    nat_id = _make_nat(ec2)
    monkeypatch.setattr(networking, "metric_sum", lambda *a, **k: 0.0)
    nats = [d for d in networking.collect(session, REGION, "111122223333") if d.check == "nat-idle"]
    assert any(d.resource_id == nat_id for d in nats)


def test_active_nat_not_flagged_when_traffic_present(session, monkeypatch):
    ec2 = session.client("ec2", region_name=REGION)
    _make_nat(ec2)
    monkeypatch.setattr(networking, "metric_sum", lambda *a, **k: 5_000_000.0)
    nats = [d for d in networking.collect(session, REGION, "111122223333") if d.check == "nat-idle"]
    assert nats == []


def test_idle_not_flagged_when_metric_has_no_datapoints(session, monkeypatch):
    # no datapoints (None) means "unknown", not "idle" — a busy resource must not be flagged
    ec2 = session.client("ec2", region_name=REGION)
    _make_nat(ec2)
    monkeypatch.setattr(networking, "metric_sum", lambda *a, **k: None)
    nats = [d for d in networking.collect(session, REGION, "111122223333") if d.check == "nat-idle"]
    assert nats == []


def test_idle_alb_flagged_when_no_requests(session, monkeypatch):
    ec2 = session.client("ec2", region_name=REGION)
    elb = session.client("elbv2", region_name=REGION)
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    subnets = [
        ec2.create_subnet(VpcId=vpc, CidrBlock=f"10.0.{i}.0/24", AvailabilityZone=f"{REGION}{az}")[
            "Subnet"
        ]["SubnetId"]
        for i, az in ((1, "a"), (2, "b"))
    ]
    elb.create_load_balancer(Name="legacy-api", Subnets=subnets, Type="application")
    monkeypatch.setattr(networking, "metric_sum", lambda *a, **k: 0.0)
    lbs = [d for d in networking.collect(session, REGION, "111122223333") if d.check == "elb-idle"]
    assert any(d.resource_id == "legacy-api" for d in lbs)
