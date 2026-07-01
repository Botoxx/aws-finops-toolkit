"""Privacy gate: replace account IDs, ARNs and resource IDs with opaque tokens before any
text leaves for the Anthropic API, and rehydrate the tokens locally in the final report.

This is about the cost *data* placed in a prompt, not credentials: credentials never leave the
machine regardless, but the findings you narrate do go to the API. This module redacts that data."""

from __future__ import annotations

import re
from collections import defaultdict

from .schema import Finding, Recommendation, Report

# Order matters: ARNs (which embed account + resource ids) are tokenised whole first.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ARN", re.compile(r"arn:aws[a-z-]*:[^\s\"']+")),
    ("ACCT", re.compile(r"\b\d{12}\b")),
    ("IP", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
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
        self._literals: set[str] = set()  # known secrets that match no pattern (bucket/LB names)

    def _token(self, kind: str, value: str) -> str:
        if value in self._rev:
            return self._rev[value]
        self._counter[kind] += 1
        tok = f"{kind}_{self._counter[kind]}"
        self.tokens[tok] = value
        self._rev[value] = tok
        return tok

    def note_secret(self, value: str | None) -> None:
        """Register a known-sensitive literal (a resource id/name) that the patterns may not match
        — e.g. an S3 bucket name or load-balancer name. Redacted by exact substring thereafter."""
        if value and value not in self._rev:
            self._token("RES", value)
            self._literals.add(value)

    def redact_text(self, text: str) -> str:
        # Known literals first (longest first), so unmatched names are tokenised before patterns run.
        for lit in sorted(self._literals, key=len, reverse=True):
            text = text.replace(lit, self._rev[lit])
        for kind, pattern in _PATTERNS:
            text = pattern.sub(lambda m: self._token(kind, m.group(0)), text)
        return text

    def rehydrate(self, text: str) -> str:
        # longest tokens first so e.g. RES_10 isn't partially clobbered by RES_1
        for tok in sorted(self.tokens, key=len, reverse=True):
            text = text.replace(tok, self.tokens[tok])
        return text

    def redact_finding(self, f: Finding) -> Finding:
        # Seed the finding's own identifiers as literals so names that match no pattern still go.
        self.note_secret(f.resource_id)
        self.note_secret(f.resource_arn)
        update = {field: self.redact_text(v) for field in _REDACTED_FIELDS if (v := getattr(f, field))}
        update["caveats"] = [self.redact_text(c) for c in f.caveats]
        return f.model_copy(update=update)

    def redact_findings(self, findings: list[Finding]) -> list[Finding]:
        redacted = [self.redact_finding(f) for f in findings]
        self.assert_no_leak(findings, redacted)
        return redacted

    def assert_no_leak(self, originals: list[Finding], redacted: list[Finding]) -> None:
        """Fail closed: verify no finding's resource_id/resource_arn survived into a field that gets
        sent to the model. Scanned over the redacted text fields only — structural fields (service,
        region, check, enums) are never redacted and may legitimately share a substring with a short
        id (e.g. a bucket named 'ec2' vs service 'ec2'), so including them would false-positive."""
        shipped = "\n".join(
            text
            for f in redacted
            for text in (*(getattr(f, fld) or "" for fld in _REDACTED_FIELDS), *f.caveats)
        )
        for f in originals:
            for secret in (f.resource_id, f.resource_arn):
                if secret and secret in shipped:
                    raise RuntimeError(f"redaction leak: {secret!r} survived into the API payload")

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
