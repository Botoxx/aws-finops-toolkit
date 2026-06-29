"""Opus 4.8 executive-summary pass (optional, highest-stakes synthesis only). Subject to the
same rule as everything else: it may only state euro figures present in the findings + total.
Output is re-checked by the numeric-validation gate."""

from __future__ import annotations

import json

from ..schema import Finding, Report

MODEL = "claude-opus-4-8"

SYSTEM = """You are writing the executive summary of an AWS cost-audit report for a CTO.
You receive the findings (with code-computed euro savings) and the code-computed total.

HARD RULES:
- State only euro figures that appear in the findings or in total_monthly_savings_eur.
- Never compute, sum, or invent a euro amount. Use the provided total for any overall figure.
- 3-5 sentences: the headline opportunity, where the money is, and the recommended first move.
- Plain, confident, no filler. Carry the dominant caveats (e.g. commitment assumptions)."""


def executive_summary(findings: list[Finding], total: float, *, client=None) -> str:
    if client is None:
        from anthropic import Anthropic

        client = Anthropic()
    payload = {
        "total_monthly_savings_eur": round(total, 2),
        "findings": [f.model_dump(mode="json") for f in findings],
    }
    msg = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM,
        messages=[{"role": "user", "content": json.dumps(payload, indent=2)}],
    )
    return "".join(b.text for b in msg.content if b.type == "text").strip()
