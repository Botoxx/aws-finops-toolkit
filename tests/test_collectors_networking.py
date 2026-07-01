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


def test_metric_sum_is_zero_when_no_datapoints():
    # a successful query with no datapoints means 'no activity' (e.g. ALB RequestCount on zero
    # requests) — it must read as 0.0 (idle), not be suppressed. Failures raise instead.
    from finops_toolkit.collectors.metrics import metric_sum

    class _CW:
        def get_metric_statistics(self, **k):
            return {"Datapoints": []}

    class _Session:
        def client(self, *a, **k):
            return _CW()

    assert metric_sum(_Session(), REGION, "AWS/ApplicationELB", "RequestCount", []) == 0.0


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


def _subnets(ec2):
    vpc = ec2.create_vpc(CidrBlock="10.0.0.0/16")["Vpc"]["VpcId"]
    return [
        ec2.create_subnet(VpcId=vpc, CidrBlock=f"10.0.{i}.0/24", AvailabilityZone=f"{REGION}{az}")[
            "Subnet"
        ]["SubnetId"]
        for i, az in ((1, "a"), (2, "b"))
    ]


def test_idle_nlb_uses_processed_bytes_on_network_namespace(session, monkeypatch):
    ec2 = session.client("ec2", region_name=REGION)
    elb = session.client("elbv2", region_name=REGION)
    elb.create_load_balancer(Name="net-lb", Subnets=_subnets(ec2), Type="network")
    seen = {}

    def fake_metric_sum(_s, _r, namespace, metric_name, *a, **k):
        seen.update(namespace=namespace, metric=metric_name)
        return 0.0

    monkeypatch.setattr(networking, "metric_sum", fake_metric_sum)
    nlbs = [
        d for d in networking.collect(session, REGION, "111122223333")
        if d.check == "elb-idle" and d.resource_id == "net-lb"
    ]
    assert nlbs and nlbs[0].pricing["lb_type"] == "network"
    # NLB must query the counter metric on the NLB namespace, not the ActiveFlowCount gauge
    assert seen == {"namespace": "AWS/NetworkELB", "metric": "ProcessedBytes"}


def test_sub_collector_failure_does_not_drop_the_region(session, monkeypatch):
    # a throttled NAT paginator must not discard the EIP findings already gathered this region
    ec2 = session.client("ec2", region_name=REGION)
    idle_eip = ec2.allocate_address(Domain="vpc")["AllocationId"]

    def boom(*a, **k):
        raise RuntimeError("Throttling")

    monkeypatch.setattr(networking, "_nat_gateways", boom)
    monkeypatch.setattr(networking, "metric_sum", lambda *a, **k: 0.0)
    dets = networking.collect(session, REGION, "111122223333")
    assert any(d.check == "eip-unassociated" and d.resource_id == idle_eip for d in dets)
    assert any(d.check == "collector-error" for d in dets)  # the NAT area surfaces a visible gap


def test_per_resource_metric_failure_becomes_gap_not_silence(session, monkeypatch):
    ec2 = session.client("ec2", region_name=REGION)
    nat_id = _make_nat(ec2)

    def boom(*a, **k):
        raise RuntimeError("Throttling")

    monkeypatch.setattr(networking, "metric_sum", boom)
    dets = networking.collect(session, REGION, "111122223333")
    # the NAT's metric query failed — it surfaces as a gap keyed to that resource, never dropped
    assert any(d.check == "collector-error" and d.resource_id == nat_id for d in dets)
