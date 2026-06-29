"""Regional list prices for the flat-rate resources v1 quantifies.

Every resource priced here is storage or networking — none is ever covered by a Savings Plan
or Reserved Instance — so the public list price IS the customer's effective price (see the Q2
reasoning in the research vault). Compute savings, where commitment coverage *would* distort
list price, are not priced here: they come pre-computed in currency from Cost Explorer and
Compute Optimizer (checks 10-11).

Figures are EUR-approximate eu-west-1 list prices (AWS bills USD; treat as indicative). They are
data, never model-recalled, and carry a 'list price' provenance in every estimate's caveat.
"""

from __future__ import annotations

HOURS_PER_MONTH = 730

# $/GB-month by EBS volume type (eu-west-1 list).
EBS_GB_MONTH: dict[str, float] = {
    "gp2": 0.116,
    "gp3": 0.0928,
    "io1": 0.145,
    "io2": 0.145,
    "st1": 0.054,
    "sc1": 0.018,
    "standard": 0.058,
}
SNAPSHOT_GB_MONTH = 0.05  # EBS snapshot standard tier, $/GB-month

# Flat hourly charges.
EIP_IDLE_HOUR = 0.005          # unassociated / extra public IPv4
NAT_GATEWAY_HOUR = 0.048       # NAT gateway hourly (eu-west-1)
ALB_HOUR = 0.0252              # ALB base hourly (LCU excluded — conservative)
NLB_HOUR = 0.0270

# Orphaned snapshots are incremental: realised saving is far below nominal size.
# We report a conservative range; the low bound assumes heavy block sharing.
SNAPSHOT_INCREMENTAL_LOW = 0.3
SNAPSHOT_INCREMENTAL_HIGH = 1.0

LIST_PRICE_CAVEAT = "Based on eu-west-1 public list price; not the customer's negotiated rate."


def ebs_gb_month(volume_type: str) -> float:
    return EBS_GB_MONTH.get(volume_type, EBS_GB_MONTH["gp2"])
