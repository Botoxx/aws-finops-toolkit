import json

from finops_toolkit.redaction import Redactor


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
