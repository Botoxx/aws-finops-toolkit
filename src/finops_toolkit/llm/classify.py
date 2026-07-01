"""Haiku 4.5 pre-rank pass: cheap severity labelling of the deterministic findings.
Optional — ordering already works in code (engine.prioritize). This adds a one-word severity
the report can surface. The model never sees or emits euro figures here; it labels only."""

from __future__ import annotations

import json

from ..schema import Finding

MODEL = "claude-haiku-4-5"

SYSTEM = """You label AWS cost findings by severity for a report. You are given findings as JSON
(id, title, effort, risk, confidence — no euro figures). Return a severity for each id, one of:
critical, high, medium, low. Base it on risk and how clear-cut the finding is. Label only."""

_SCHEMA = {
    "type": "object",
    "properties": {
        "labels": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "severity": {"enum": ["critical", "high", "medium", "low"]},
                },
                "required": ["id", "severity"],
            },
        }
    },
    "required": ["labels"],
}


def classify_findings(findings: list[Finding], *, client=None) -> dict[str, str]:
    if client is None:
        from anthropic import Anthropic

        client = Anthropic()
    slim = [
        {"id": f.id, "title": f.title, "effort": f.effort.value, "risk": f.risk.value,
         "confidence": f.confidence.value}
        for f in findings
    ]
    msg = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM,
        tools=[{"name": "emit_labels", "description": "Severity labels.", "input_schema": _SCHEMA}],
        tool_choice={"type": "tool", "name": "emit_labels"},
        messages=[{"role": "user", "content": json.dumps(slim)}],
    )
    block = next((b for b in msg.content if b.type == "tool_use"), None)
    if block is None or "labels" not in getattr(block, "input", {}):
        return {}  # optional pass: a malformed/text-only response degrades to no labels, never raises
    return {item["id"]: item["severity"] for item in block.input["labels"]}
