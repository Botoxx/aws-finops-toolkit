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
    report: Report | None  # None when the gate exhausted retries — narrative is withheld
    attempts: int
    violations: list[Violation]  # empty unless the gate exhausted its retries
    opus_summary_rejected: bool = False  # True when a requested Opus summary failed the gate and
    # was dropped in favour of the Sonnet summary — the caller can surface that it did not take effect


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

    if violations:
        # The gate could not clear every figure within max_attempts. Refuse to ship a narrative
        # that still contains rejected figures — the caller falls back to the deterministic report.
        return SecureReport(None, attempts, violations)

    opus_summary_rejected = False
    if use_opus_summary:
        total = report.total_monthly_savings_eur
        summary = executive_summary(redacted, total, client=client)
        candidate = report.model_copy(update={"executive_summary": summary})
        if not validate_report(candidate, redacted):  # only adopt if it passes the gate
            report = candidate
        else:
            # the Opus summary tripped the gate — keep the validated Sonnet summary and say so,
            # rather than silently returning Sonnet prose as though Opus had been adopted
            opus_summary_rejected = True

    report = redactor.rehydrate_report(report)
    return SecureReport(report, attempts, violations, opus_summary_rejected)
