# aws-finops-toolkit

Find what's wasting money in your AWS account, get a plain-English remediation report.

Built for SaaS companies with €20k–200k/yr AWS bills who don't have a dedicated FinOps team.

## What it finds

| Category | Checks |
|----------|--------|
| **Compute** | Idle EC2 instances (< 5% CPU 7d avg), oversized instance types, unused Elastic IPs |
| **Storage** | Unattached EBS volumes, S3 buckets without lifecycle rules, old snapshots |
| **Networking** | Underutilised NAT Gateways, idle load balancers |
| **Database** | RDS instances with < 10% CPU over 7 days, unencrypted snapshots |
| **Spend** | Anomaly detection deltas vs prior 30-day baseline |

## Output

1. **JSON findings file** — machine-readable, CI/CD friendly  
2. **Markdown cost report** — estimated monthly savings per finding  
3. **LLM remediation narrative** — plain-English summary of top 5 actions, generated via Claude API

### Example report excerpt

```
## Top findings — estimated savings: €1,840/month

### 1. 3 unattached EBS volumes (gp2, 500GB total) — €47/month
These volumes are not attached to any instance and have not been accessed in 45+ days.
Safe to snapshot and delete unless tied to a manual backup process.
Recommended action: aws ec2 delete-volume --volume-id <id>

### 2. NAT Gateway eu-west-1a — €127/month, 0.2GB/day throughput
...
```

## Usage

```bash
pip install -r requirements.txt

# Set AWS credentials (read-only IAM policy provided in iam/)
export AWS_PROFILE=finops-readonly

# Run audit
python audit.py --region eu-west-1 --output findings.json

# Generate report (requires ANTHROPIC_API_KEY)
python report.py --findings findings.json --output report.md
```

## Required IAM permissions

A least-privilege read-only IAM policy is included in `iam/finops-readonly-policy.json`.  
No write permissions required for the audit phase.

## Terraform module (optional)

Deploy the toolkit as a scheduled Lambda + S3 report delivery:

```bash
cd terraform/
terraform apply
# Runs weekly, delivers report to S3 and optionally Slack
```

## Status

🚧 Work in progress — EC2, EBS, and NAT Gateway checks complete. RDS and S3 checks in progress.

---

*Part of the [Apex Lab](https://github.com/Botoxx) cloud engineering portfolio.  
Interested in a managed FinOps audit for your AWS account? [Get in touch.](https://linkedin.com/in/botond-geiszt-82b91b167)*
