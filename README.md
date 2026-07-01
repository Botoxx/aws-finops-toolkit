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
| 5 | Orphaned snapshots (source gone) | `describe-snapshots` | medium (detect deterministic, € ranged) |
| 6 | Unused AMIs (+ backing snapshots) | `describe-images` | high |
| 7 | S3 incomplete multipart uploads | `list-multipart-uploads` | medium (detect only) |
| 8 | Idle NAT gateways | CloudWatch `BytesOutToDestination` | medium |
| 9 | Idle load balancers | CloudWatch `RequestCount`/`ProcessedBytes` | medium |
| 10 | Savings Plans / RI coverage gap | Cost Explorer | high (AWS-sourced) |
| 11 | EC2 rightsizing | Compute Optimizer | high (AWS-sourced) |

## Output

1. **`findings.json`** — machine-readable, the typed contract every figure flows through.
2. **`report.md`** — prioritized (safe quick wins first), with per-finding savings where
   quantifiable (some checks, e.g. incomplete-MPU, are detect-only), caveats, and an optional
   Claude-generated executive summary + recommendations.

## Usage

```bash
# install (uv recommended)
uv sync            # or: pip install -e .

# read-only credentials — least-privilege policy provided in iam/
export AWS_PROFILE=finops-readonly

# run the audit (single command, no resources are modified) — writes findings.json + report.md
finops-toolkit audit --region eu-west-1 --out-dir ./out

# the same command adds a Claude-written narrative to report.md when a key is set
# (no key → the deterministic report is still written; --no-narrative skips it explicitly)
export ANTHROPIC_API_KEY=sk-ant-...
finops-toolkit audit --region eu-west-1 --out-dir ./out
```

Cross-account (recommended for engagements): assume a read-only role with an ExternalId.

```bash
finops-toolkit audit --role-arn arn:aws:iam::ACCOUNT:role/finops-readonly \
                     --external-id <shared-secret> --region eu-west-1
```

## Required IAM permissions

A least-privilege, read-only policy is in `iam/finops-readonly-policy.json`. It grants only the
specific describe/get/list actions the collectors actually call (EC2, ELB, S3 listing, CloudWatch
`GetMetricStatistics`, STS `GetCallerIdentity`) plus Cost Explorer / Compute Optimizer reads, and
adds an explicit `Deny` on anything outside that read set. The policy grants **no** write action,
so for a principal using it, a bug in this code has nothing to call — the read-only property is a
property of the granted credentials, not a claim about the code. (This is an identity policy; it
does not override SCPs or resource-based policies that grant writes elsewhere.)

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
