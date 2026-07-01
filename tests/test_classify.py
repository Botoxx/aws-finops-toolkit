from types import SimpleNamespace

from finops_toolkit.llm.classify import classify_findings


class _FakeClient:
    def __init__(self, labels):
        self._labels = labels
        self.messages = self

    def create(self, **kwargs):
        self.captured = kwargs
        block = SimpleNamespace(type="tool_use", name="emit_labels", input={"labels": self._labels})
        return SimpleNamespace(content=[block])


def test_classify_degrades_to_empty_on_text_only_response(findings):
    # optional pass: a text-only / truncated model reply must degrade to no labels, never StopIteration
    class _NoToolClient:
        def __init__(self):
            self.messages = self

        def create(self, **kwargs):
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="hi")])

    assert classify_findings(findings[:2], client=_NoToolClient()) == {}


def test_classify_returns_id_to_severity_map(findings):
    labels = [{"id": f.id, "severity": "high"} for f in findings[:2]]
    client = _FakeClient(labels)
    result = classify_findings(findings[:2], client=client)
    assert result == {findings[0].id: "high", findings[1].id: "high"}
    # findings sent to Haiku carry no euro figures
    sent = client.captured["messages"][0]["content"]
    assert "monthly_savings" not in sent and "€" not in sent
