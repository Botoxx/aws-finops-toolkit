"""Offline test of the report generation wiring using a fake Anthropic client:
schema is valid as a tool input_schema, tool_use is parsed, and code owns the total."""

from types import SimpleNamespace

from finops_toolkit.llm.report import generate_report
from finops_toolkit.schema import Report


class _FakeMessages:
    def __init__(self, payload):
        self._payload = payload
        self.captured = {}

    def create(self, **kwargs):
        self.captured = kwargs
        block = SimpleNamespace(type="tool_use", name="emit_report", input=self._payload)
        return SimpleNamespace(content=[block])


class _FakeClient:
    def __init__(self, payload):
        self.messages = _FakeMessages(payload)


def test_generate_report_parses_and_owns_total(findings):
    # model deliberately reports a wrong total; code must overwrite it
    model_output = {
        "executive_summary": "Summary.",
        "total_monthly_savings_eur": 9999.99,
        "recommendations": [
            {
                "finding_id": "ebs-unattached-001",
                "headline": "Delete unattached volume",
                "rationale": "Idle 47 days.",
                "action": "Snapshot then delete.",
            }
        ],
    }
    client = _FakeClient(model_output)
    report = generate_report(findings, client=client)

    expected_total = round(sum(f.monthly_savings_eur for f in findings), 2)
    assert isinstance(report, Report)
    assert report.total_monthly_savings_eur == expected_total  # code owns it, not 9999.99

    # the forced tool-call wiring is correct
    cap = client.messages.captured
    assert cap["model"] == "claude-sonnet-4-6"
    assert cap["tool_choice"] == {"type": "tool", "name": "emit_report"}
    assert cap["tools"][0]["input_schema"]["title"] == "Report"
