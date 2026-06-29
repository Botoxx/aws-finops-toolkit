"""Privacy gate: replace account IDs, ARNs and resource IDs with opaque tokens before any
text leaves for the Anthropic API, and rehydrate the tokens locally in the final report.

'Credentials never leave your machine' (the MCP claim) is about credentials, not the cost
*data* you then put in a prompt — that still goes to the API. This module redacts that data."""

from __future__ import annotations

import re
from collections import defaultdict

from .schema import Finding, Recommendation, Report

# Order matters: ARNs (which embed account + resource ids) are tokenised whole first.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ARN", re.compile(r"arn:aws[a-z-]*:[^\s\"']+")),
    ("ACCT", re.compile(r"\b\d{12}\b")),
    (
        "RES",
        re.compile(r"\b(?:vol|i|snap|ami|eipalloc|eni|nat|subnet|vpc)-[0-9a-f]{8,17}\b"),
    ),
]

_REDACTED_FIELDS = ("id", "resource_id", "resource_arn", "title", "evidence", "confidence_reason")


class Redactor:
    """Stateful, consistent tokeniser: the same original value always maps to the same token."""

    def __init__(self) -> None:
        self.tokens: dict[str, str] = {}  # token -> original
        self._rev: dict[str, str] = {}    # original -> token
        self._counter: dict[str, int] = defaultdict(int)

    def _token(self, kind: str, value: str) -> str:
        if value in self._rev:
            return self._rev[value]
        self._counter[kind] += 1
        tok = f"{kind}_{self._counter[kind]}"
        self.tokens[tok] = value
        self._rev[value] = tok
        return tok

    def redact_text(self, text: str) -> str:
        for kind, pattern in _PATTERNS:
            text = pattern.sub(lambda m: self._token(kind, m.group(0)), text)
        return text

    def rehydrate(self, text: str) -> str:
        # longest tokens first so e.g. RES_10 isn't partially clobbered by RES_1
        for tok in sorted(self.tokens, key=len, reverse=True):
            text = text.replace(tok, self.tokens[tok])
        return text

    def redact_finding(self, f: Finding) -> Finding:
        update = {field: self.redact_text(v) for field in _REDACTED_FIELDS if (v := getattr(f, field))}
        update["caveats"] = [self.redact_text(c) for c in f.caveats]
        return f.model_copy(update=update)

    def redact_findings(self, findings: list[Finding]) -> list[Finding]:
        return [self.redact_finding(f) for f in findings]

    def rehydrate_report(self, report: Report) -> Report:
        return report.model_copy(
            update={
                "executive_summary": self.rehydrate(report.executive_summary),
                "recommendations": [
                    Recommendation(
                        finding_id=self.rehydrate(r.finding_id),
                        headline=self.rehydrate(r.headline),
                        rationale=self.rehydrate(r.rationale),
                        action=self.rehydrate(r.action),
                    )
                    for r in report.recommendations
                ],
            }
        )
