import json

import boto3
from moto import mock_aws
from typer.testing import CliRunner

from finops_toolkit.cli import app

runner = CliRunner()


def test_cli_audit_writes_findings_and_report(tmp_path):
    with mock_aws():
        ec2 = boto3.client("ec2", region_name="eu-west-1")
        ec2.create_volume(AvailabilityZone="eu-west-1a", Size=100, VolumeType="gp2")
        ec2.allocate_address(Domain="vpc")
        result = runner.invoke(
            app,
            ["audit", "--region", "eu-west-1", "--out-dir", str(tmp_path), "--no-narrative"],
        )

    assert result.exit_code == 0, result.output
    findings = json.loads((tmp_path / "findings.json").read_text())
    assert findings, "expected at least one finding"
    report = (tmp_path / "report.md").read_text()
    assert report.startswith("# AWS FinOps Audit")
    assert "addressable waste" in report
