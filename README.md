# aws-finops-toolkit

Find what's wasting money in your AWS account, get a plain-English remediation report.

Built for SaaS companies with €20k–200k/yr AWS bills who don't have a dedicated FinOps team.

**Read-only by construction. Every euro figure is computed in code; Claude only narrates.**

## How it works

```
read-only scan (boto3)  →  deterministic findings[]  →  savings math (code)  →  report
                                                            │
                                                  Claude narrates the findings
                                              (numeric-validation gate: no invented €)
```

- **Detection is deterministic.** No "low CPU = idle" guesswork. Findings are either provable
  orphans (unattached, idle-by-existence) or AWS's own recommendations (Compute Optimizer,
  Cost Explorer).
- **Savings are computed in code** on public list prices — and storage/networking resources are
  never Savings-Plan/RI-covered, so list price *is* the effective rate. Compute savings come from
  AWS Cost Explorer / Compute Optimizer directly.
- **Claude writes the report, not the numbers.** Findings are redacted (account IDs, ARNs,
  resource IDs → tokens) before any API call, then a numeric-validation gate rejects any euro
  figure in the narrative that isn't in `findings[]`.

## v1 checks

| # | Check | Source | Confidence |
|---|-------|--------|------------|
| 1 | Unattached EBS volumes | `describe-volumes` | high |
| 2 | gp2 → gp3 migration opportunity | `describe-volumes` | high |
| 3 | Unassociated Elastic IPs | `describe-addresses` | high |
| 4 | EBS volumes on stopped instances | `describe-volumes` + instances | high |
| 5 | Orphaned snapshots (source gone) | `describe-snapshots` | high detect / ranged € |
| 6 | Unused AMIs (+ backing snapshots) | `describe-images` | high |
| 7 | S3 incomplete multipart uploads | `list-multipart-uploads` | high detect |
| 8 | Idle NAT gateways | CloudWatch `BytesOutToDestination` | med-high |
| 9 | Idle load balancers | CloudWatch | med-high |
| 10 | Savings Plans / RI coverage gap | Cost Explorer | high (AWS-sourced) |
| 11 | EC2 rightsizing | Compute Optimizer | high (AWS-sourced) |

## Output

1. **`findings.json`** — machine-readable, the typed contract every figure flows through.
2. **`report.md`** — prioritized (safe quick wins first), with per-finding savings, caveats, and
   an optional Claude-generated executive summary + recommendations.

## Usage

```bash
# install (uv recommended)
uv sync            # or: pip install -e .

# read-only credentials — least-privilege policy provided in iam/
export AWS_PROFILE=finops-readonly

# run the audit (no resources are modified)
finops-toolkit audit --region eu-west-1 --out-dir ./out

# add the Claude narrative (bring your own key)
export ANTHROPIC_API_KEY=sk-ant-...
finops-toolkit audit --region eu-west-1 --out-dir ./out
```

Cross-account (recommended for engagements): assume a read-only role with an ExternalId.

```bash
finops-toolkit audit --role-arn arn:aws:iam::ACCOUNT:role/finops-readonly \
                     --external-id <shared-secret> --region eu-west-1
```

## Required IAM permissions

A least-privilege, read-only policy is in `iam/finops-readonly-policy.json`. It allows only
describe/get/list across the services scanned, plus Cost Explorer / Compute Optimizer reads, and
**explicitly denies every other action** — so even a bug cannot mutate. No write permissions are
requested.

## Privacy

Cost data carries account IDs, ARNs, and tag values. Before any call to the Anthropic API, those
are replaced with opaque tokens and rehydrated locally — only aggregated, redacted findings leave
your machine. Use your own Anthropic key (or Bedrock to keep the call in-account).

## Status

🚧 Work in progress — a real reference implementation, not a polished product. The 11 checks above
are implemented with a deterministic test suite (moto + botocore Stubber). Utilization-based idle
detection, S3 lifecycle, Graviton, and CUR-based cost allocation are planned for v2.

## Models

Claude Sonnet 4.6 writes the report; Claude Opus 4.8 is an optional executive-summary pass;
Claude Haiku 4.5 handles cheap severity labelling. The numeric-validation gate applies to all.

---

*Part of the [cloudgeist](https://cloudgeist.cloud) cloud engineering portfolio — [github.com/Botoxx](https://github.com/Botoxx).
Interested in a managed FinOps audit for your AWS account? [Get a FinOps audit →](https://cloudgeist.cloud/finops-audit/)*
