"""The `findings[]` contract — the single source of truth between the deterministic
core and every LLM / delivery surface. Every euro figure originates here, in code."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


class Category(str, Enum):
    compute = "compute"
    storage = "storage"
    networking = "networking"
    database = "database"
    commitment = "commitment"
    other = "other"


class Effort(str, Enum):
    trivial = "trivial"
    low = "low"
    medium = "medium"
    high = "high"


class Risk(str, Enum):
    safe = "safe"
    caution = "caution"
    destructive = "destructive"


class Confidence(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class Finding(BaseModel):
    """One unit of detected waste. Every euro figure is computed in code: storage/networking on
    public list price (never SP/RI-covered, so list price is the effective rate), and compute from
    AWS Cost Explorer / Compute Optimizer's own currency estimates. The LLM computes nothing."""

    id: str = Field(description="Stable finding id, e.g. 'ebs-unattached-001'.")
    check: str = Field(description="Check slug, e.g. 'ebs-unattached'.")
    service: str = Field(description="AWS service, e.g. 'ec2', 's3'.")
    category: Category
    title: str = Field(description="Short human-readable label.")
    resource_id: str = Field(description="Short resource identifier (vol-…, eipalloc-…).")
    resource_arn: str | None = None
    region: str
    evidence: str = Field(description="Why this was flagged, in plain language.")

    monthly_savings_eur: float = Field(ge=0)
    savings_low_eur: float | None = Field(default=None, ge=0)
    savings_high_eur: float | None = Field(default=None, ge=0)

    effort: Effort
    risk: Risk
    confidence: Confidence
    confidence_reason: str
    auto_applyable: bool = False
    caveats: list[str] = Field(default_factory=list)

    @field_validator("monthly_savings_eur", "savings_low_eur", "savings_high_eur")
    @classmethod
    def _round_money(cls, v: float | None) -> float | None:
        return None if v is None else round(v, 2)

    @model_validator(mode="after")
    def _bounds(self) -> "Finding":
        lo, hi = self.savings_low_eur, self.savings_high_eur
        if (lo is None) != (hi is None):
            raise ValueError("savings bounds must be set as a pair (both or neither)")
        if lo is not None and not (lo <= self.monthly_savings_eur <= hi):
            raise ValueError("require savings_low_eur <= monthly_savings_eur <= savings_high_eur")
        return self

    def allowed_figures(self) -> set[float]:
        """Euro figures the narrative is permitted to cite for this finding."""
        return {
            round(x, 2)
            for x in (self.monthly_savings_eur, self.savings_low_eur, self.savings_high_eur)
            if x is not None
        }


class Detection(BaseModel):
    """A collector's output: the detection-time facts about one wasteful resource, with the
    raw inputs the savings layer needs (`pricing`). Carries no euro figure — `priced()` turns
    it into a Finding once savings.py has computed the amount."""

    id: str
    check: str
    service: str
    category: Category
    title: str
    resource_id: str
    resource_arn: str | None = None
    region: str
    evidence: str
    effort: Effort
    risk: Risk
    confidence: Confidence
    confidence_reason: str
    auto_applyable: bool = False
    caveats: list[str] = Field(default_factory=list)
    pricing: dict = Field(default_factory=dict, description="Raw savings inputs; not shipped.")

    def priced(
        self, monthly: float, low: float | None = None, high: float | None = None
    ) -> Finding:
        return Finding(
            **self.model_dump(exclude={"pricing"}),
            monthly_savings_eur=monthly,
            savings_low_eur=low,
            savings_high_eur=high,
        )


class Recommendation(BaseModel):
    """One narrative item produced by the LLM, bound to a finding by id.
    The LLM writes prose; it may only cite euro figures that exist in the finding."""

    finding_id: str
    headline: str
    rationale: str
    action: str


class Report(BaseModel):
    """The client-facing deliverable. `total_monthly_savings_eur` is computed by code,
    never by the model; the LLM fills `executive_summary` and `recommendations`."""

    executive_summary: str
    total_monthly_savings_eur: float = Field(ge=0)
    recommendations: list[Recommendation] = Field(default_factory=list)

    def allowed_figures(self, findings: list[Finding]) -> set[float]:
        figs: set[float] = {round(self.total_monthly_savings_eur, 2)}
        for f in findings:
            figs |= f.allowed_figures()
        return figs
