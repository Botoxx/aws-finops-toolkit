"""Offline test of the secure pipeline with a fake Anthropic client that echoes the redacted
payload back as a report. Proves: (1) no raw secret reaches the API, (2) redacted tokens in the
model's output are rehydrated to real values locally, (3) the numeric gate passes clean output."""

import json
from types import SimpleNamespace

from finops_toolkit.llm.pipeline import generate_secure_report


class _FakeMessages:
    def __init__(self):
        self.captured_content = None

    def create(self, **kwargs):
        content = kwargs["messages"][0]["content"]
        self.captured_content = content
        payload = json.loads(content.split("Findings:\n", 1)[1])
        total = payload["total_monthly_savings_eur"]
        f0 = payload["findings"][0]
        report_input = {
            "executive_summary": f"Total addressable waste is €{total}/month.",
            "total_monthly_savings_eur": total,
            "recommendations": [
                {
                    "finding_id": f0["id"],
                    "headline": f0["title"],
                    "rationale": f"This saves €{f0['monthly_savings_eur']} per month.",
                    "action": f"Action on resource {f0['resource_id']}.",  # a redacted token
                }
            ],
        }
        block = SimpleNamespace(type="tool_use", name="emit_report", input=report_input)
        return SimpleNamespace(content=[block])


class _FakeClient:
    def __init__(self):
        self.messages = _FakeMessages()


def test_secure_pipeline_redacts_outbound_and_rehydrates_result(findings):
    client = _FakeClient()
    result = generate_secure_report(findings, client=client)

    # (1) the payload that went to the API carries no raw secrets
    sent = client.messages.captured_content
    assert "111122223333" not in sent
    assert "arn:aws" not in sent
    assert "vol-0a1b2c3d4e5f60011" not in sent

    # (2) the rehydrated report restores the real resource id (the model only ever saw a token)
    action = result.report.recommendations[0].action
    assert "vol-0a1b2c3d4e5f60011" in action
    assert "RES_" not in action

    # (3) gate passed — total + cited figure are both real
    assert result.violations == []
    assert result.report.total_monthly_savings_eur == round(
        sum(f.monthly_savings_eur for f in findings), 2
    )
