"""Sonnet 4.6 report generation over the findings[] contract via structured output.
The model narrates and orders; the euro total is owned by code. Figures the model writes
are checked by the numeric-validation gate (see validate.py)."""

from __future__ import annotations

import json

from ..schema import Finding, Report
from .validate import Violation, validate_report

MODEL = "claude-sonnet-4-6"


class ReportGenerationError(RuntimeError):
    """The model returned no usable report tool_use block (text-only reply, refusal, or a
    max_tokens truncation before the tool call). Treated as a failed attempt, never a crash."""

SYSTEM = """You are a senior AWS FinOps consultant writing a client-ready cost-audit report.
You receive findings as JSON; each finding carries a code-computed euro saving.

HARD RULES:
- You may ONLY state euro figures that appear verbatim in the findings data or in the provided
  total_monthly_savings_eur. NEVER compute, sum, average, round, or invent a euro amount.
- Write every euro figure with a leading € and no thousands separators (e.g. €47.00, €1840.50).
  Never state a euro amount as a bare number, and never use $ or any non-euro currency.
- To state an overall total, use the provided total_monthly_savings_eur and nothing else.
- Every recommendation must set finding_id to a real finding id.
- Order recommendations by impact and ease: safe, high-confidence quick wins first; large or
  riskier levers afterwards, clearly flagged as recommend-only.
- Carry each finding's caveats and confidence into the rationale. Do not overstate.
- Write for a non-specialist CTO: concrete, plain-spoken, no filler."""


def _total(findings: list[Finding]) -> float:
    return round(sum(f.monthly_savings_eur for f in findings), 2)


def generate_report(findings: list[Finding], *, client=None) -> Report:
    """Single generation. Code owns the total; the model owns prose + ordering."""
    if client is None:
        from anthropic import Anthropic

        client = Anthropic()

    total = _total(findings)
    payload = {
        "total_monthly_savings_eur": total,
        "findings": [f.model_dump(mode="json") for f in findings],
    }
    msg = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM,
        tools=[
            {
                "name": "emit_report",
                "description": "Emit the structured client-facing audit report.",
                "input_schema": Report.model_json_schema(),
            }
        ],
        tool_choice={"type": "tool", "name": "emit_report"},
        messages=[{"role": "user", "content": "Findings:\n" + json.dumps(payload, indent=2)}],
    )
    block = next((b for b in msg.content if b.type == "tool_use"), None)
    if block is None:
        raise ReportGenerationError("model returned no emit_report tool_use block")
    report = Report.model_validate(block.input)
    report.total_monthly_savings_eur = total  # code owns the total, not the model
    return report


def generate_validated_report(
    findings: list[Finding], *, client=None, max_attempts: int = 3
) -> tuple[Report | None, int, list[Violation]]:
    """Regenerate until the numeric gate passes or attempts exhaust. Returns
    (report, attempts_used, final_violations). On exhaustion the report may be None (generation
    itself failed) or a report that still has violations — either way violations is non-empty, so
    the caller withholds the narrative. A clean pass returns a real report with no violations."""
    report: Report | None = None
    violations: list[Violation] = []
    for attempt in range(1, max_attempts + 1):
        try:
            report = generate_report(findings, client=client)
        except ReportGenerationError as e:
            report, violations = None, [Violation(0.0, f"report generation failed: {e}")]
            continue
        violations = validate_report(report, findings)
        if not violations:
            return report, attempt, []
    return report, max_attempts, violations
