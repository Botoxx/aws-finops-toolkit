"""Numeric-validation gate: parse every currency figure out of the narrative and assert
it exists in the findings. Any figure the model invented or computed -> violation ->
caller regenerates. This is the mechanism behind the 'no hallucinated numbers' guarantee."""

from __future__ import annotations

import re
from typing import NamedTuple

from ..schema import Finding, Report

# Currency figures only — counts like "3 volumes" / "500 GB" / "47 days" are intentionally not
# policed. The product is EUR-only: euro figures (€/EUR/euro(s)) are validated against findings[];
# any foreign-currency figure ($/USD/dollar(s)) is a violation regardless of value, because a
# EUR report should never state one and its number is compared in the same space as euros.
# Residual limitation: a fabricated bare number with NO currency marker ("saves 999 monthly") is
# not caught here — the system prompts require a currency marker on every euro figure, so this is
# a prompt-bounded, documented gap, not a silent one. Commas = thousands separators.
_AMOUNT = r"(\d[\d,]*(?:\.\d+)?)"
_EUR = r"(?:€|\bEUR\b|\beuros?\b)"
_FOREIGN = r"(?:\$|\bUSD\b|\bdollars?\b)"
_EUR_RE = re.compile(rf"{_EUR}\s?{_AMOUNT}|{_AMOUNT}\s?{_EUR}", re.IGNORECASE)
_FOREIGN_RE = re.compile(rf"{_FOREIGN}\s?{_AMOUNT}|{_AMOUNT}\s?{_FOREIGN}", re.IGNORECASE)


class Violation(NamedTuple):
    figure: float
    snippet: str


def _parse(num: str) -> float:
    return round(float(num.replace(",", "")), 2)


def _figures(pattern: re.Pattern, text: str) -> list[float]:
    return [_parse(m.group(1) or m.group(2)) for m in pattern.finditer(text)]


def extract_currency_figures(text: str) -> list[float]:
    """Euro figures in the text. Foreign-currency figures are excluded here (they are never valid)."""
    return _figures(_EUR_RE, text)


def extract_foreign_figures(text: str) -> list[float]:
    """Non-euro currency figures — always violations in a EUR-only report."""
    return _figures(_FOREIGN_RE, text)


def _report_texts(report: Report) -> list[str]:
    parts = [report.executive_summary]
    for r in report.recommendations:
        parts += [r.headline, r.rationale, r.action]
    return parts


def validate_report(
    report: Report, findings: list[Finding], tol: float = 0.01
) -> list[Violation]:
    """Return every euro figure not in findings[], plus every foreign-currency figure (which is
    never permitted in a EUR-only report)."""
    allowed = report.allowed_figures(findings)
    violations: list[Violation] = []
    for text in _report_texts(report):
        snippet = text if len(text) <= 160 else text[:157] + "..."
        for fig in extract_currency_figures(text):
            if not any(abs(fig - a) <= tol for a in allowed):
                violations.append(Violation(fig, snippet))
        for fig in extract_foreign_figures(text):
            violations.append(Violation(fig, snippet))  # foreign currency: always a violation
    for bad_id in report.unknown_finding_ids(findings):
        violations.append(Violation(0.0, f"recommendation references unknown finding_id {bad_id!r}"))
    return violations
