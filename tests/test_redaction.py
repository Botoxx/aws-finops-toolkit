import json

from finops_toolkit.redaction import Redactor
from finops_toolkit.schema import Finding, Recommendation, Report


def test_redaction_removes_secrets_from_serialized_findings(findings):
    redactor = Redactor()
    redacted = redactor.redact_findings(findings)
    blob = json.dumps([f.model_dump(mode="json") for f in redacted])

    assert "111122223333" not in blob          # account id
    assert "arn:aws" not in blob                # ARNs
    assert "vol-0a1b2c3d4e5f60011" not in blob  # resource ids
    assert "eipalloc-" not in blob
    assert "nat-0a1b2c3d4e5f60099" not in blob
    # numbers must survive untouched — the savings math depends on them
    assert any(f.monthly_savings_eur == 47.0 for f in redacted)


def test_redaction_is_consistent_and_reversible(findings):
    redactor = Redactor()
    redactor.redact_findings(findings)
    original = "Delete arn:aws:ec2:eu-west-1:111122223333:volume/vol-0a1b2c3d4e5f60011 now."
    redacted = redactor.redact_text(original)
    assert "111122223333" not in redacted and "arn:aws" not in redacted
    # same value -> same token across calls
    assert redactor.redact_text(original) == redacted
    assert redactor.rehydrate(redacted) == original


def test_arn_tokenised_without_leaking_embedded_account_or_resource():
    # the spec's hard case: an ARN that embeds both an account id and a resource id
    r = Redactor()
    s = "arn:aws:ec2:eu-west-1:111122223333:volume/vol-0a1b2c3d4e5f60011"
    red = r.redact_text(s)
    assert "111122223333" not in red and "vol-" not in red
    assert r.rehydrate(red) == s


def test_redaction_covers_unmatched_names_and_public_ip():
    # bucket names, LB names and public IPv4s match no pattern — value-based redaction must catch them
    r = Redactor()
    f = Finding(
        id="s3-incomplete-mpu-acme-prod-billing", check="s3-incomplete-mpu", service="s3",
        category="storage", title="bucket acme-prod-billing",
        resource_id="acme-prod-billing", resource_arn="arn:aws:s3:::acme-prod-billing",
        region="eu-west-1",
        evidence="Elastic IP 52.31.18.4 idle; bucket acme-prod-billing still billed.",
        monthly_savings_eur=0.0, effort="trivial", risk="safe", confidence="medium",
        confidence_reason="x",
    )
    blob = r.redact_finding(f).model_dump_json()
    assert "acme-prod-billing" not in blob
    assert "52.31.18.4" not in blob


def test_rehydrate_report_restores_every_field(findings):
    r = Redactor()
    r.redact_findings(findings)  # seeds tokens for the fixture's identifiers
    tok = r.redact_text("vol-0a1b2c3d4e5f60011")
    assert tok != "vol-0a1b2c3d4e5f60011"
    rep = Report(
        executive_summary=f"See {tok}.",
        total_monthly_savings_eur=0.0,
        recommendations=[
            Recommendation(finding_id=tok, headline=f"h {tok}", rationale=f"r {tok}", action=f"a {tok}")
        ],
    )
    out = r.rehydrate_report(rep)
    rec = out.recommendations[0]
    assert "vol-0a1b2c3d4e5f60011" in out.executive_summary
    assert all(
        "vol-0a1b2c3d4e5f60011" in v for v in (rec.finding_id, rec.headline, rec.rationale, rec.action)
    )
    assert "RES_" not in out.executive_summary
