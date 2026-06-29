"""Numeric-validation gate: parse every currency figure out of the narrative and assert
it exists in the findings. Any figure the model invented or computed -> violation ->
caller regenerates. This is the mechanism behind the 'no hallucinated numbers' guarantee."""

from __future__ import annotations

import re
from typing import NamedTuple

from ..schema import Finding, Report

# Currency figures only — counts like "3 volumes" / "500 GB" / "47 days" are intentionally
# not policed. Matches €/$/EUR/USD as prefix or suffix; commas = thousands separators.
_CURRENCY = re.compile(
    r"(?:€|\$|EUR|USD)\s?(\d[\d,]*(?:\.\d+)?)"
    r"|(\d[\d,]*(?:\.\d+)?)\s?(?:€|\$|EUR|USD)",
    re.IGNORECASE,
)


class Violation(NamedTuple):
    figure: float
    snippet: str


def _parse(num: str) -> float:
    return round(float(num.replace(",", "")), 2)


def extract_currency_figures(text: str) -> list[float]:
    return [_parse(m.group(1) or m.group(2)) for m in _CURRENCY.finditer(text)]


def _report_texts(report: Report) -> list[str]:
    parts = [report.executive_summary]
    for r in report.recommendations:
        parts += [r.headline, r.rationale, r.action]
    return parts


def validate_report(
    report: Report, findings: list[Finding], tol: float = 0.01
) -> list[Violation]:
    """Return every currency figure in the narrative that is not a known finding figure."""
    allowed = report.allowed_figures(findings)
    violations: list[Violation] = []
    for text in _report_texts(report):
        for fig in extract_currency_figures(text):
            if not any(abs(fig - a) <= tol for a in allowed):
                snippet = text if len(text) <= 160 else text[:157] + "..."
                violations.append(Violation(fig, snippet))
    return violations
