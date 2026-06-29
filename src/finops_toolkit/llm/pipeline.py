"""The end-to-end LLM pipeline: redact findings -> generate report under the numeric gate ->
rehydrate tokens locally. Redaction means no raw ARN / account id / resource id ever reaches
the API; the gate means no euro figure in the prose was invented by the model."""

from __future__ import annotations

from typing import NamedTuple

from ..redaction import Redactor
from ..schema import Finding, Report
from .report import generate_validated_report
from .summary import executive_summary
from .validate import Violation, validate_report


class SecureReport(NamedTuple):
    report: Report
    attempts: int
    violations: list[Violation]  # empty unless the gate exhausted its retries


def generate_secure_report(
    findings: list[Finding],
    *,
    client=None,
    max_attempts: int = 3,
    use_opus_summary: bool = False,
) -> SecureReport:
    redactor = Redactor()
    redacted = redactor.redact_findings(findings)

    report, attempts, violations = generate_validated_report(
        redacted, client=client, max_attempts=max_attempts
    )

    if use_opus_summary:
        total = report.total_monthly_savings_eur
        summary = executive_summary(redacted, total, client=client)
        candidate = report.model_copy(update={"executive_summary": summary})
        if not validate_report(candidate, redacted):  # only adopt if it passes the gate
            report = candidate

    report = redactor.rehydrate_report(report)
    return SecureReport(report, attempts, violations)
