from finops_toolkit.render import render_markdown, total_savings
from finops_toolkit.schema import Recommendation, Report


def test_render_deterministic_report_without_narrative(findings):
    md = render_markdown(findings)
    assert md.startswith("# AWS FinOps Audit")
    assert "Findings (prioritized" in md
    assert findings[0].title in md
    # ranged finding renders as a band
    assert "€12.00–€32.00" in md
    # no executive summary / recommended actions when there is no LLM report
    assert "## Executive summary" not in md
    assert "## Recommended actions" not in md


def test_render_includes_narrative_when_report_present(findings):
    report = Report(
        executive_summary="The biggest lever is your Savings Plans coverage gap.",
        total_monthly_savings_eur=total_savings(findings),
        recommendations=[
            Recommendation(
                finding_id="ebs-gp2-gp3-001",
                headline="Migrate gp2 volumes to gp3",
                rationale="Zero-downtime, ~20% cheaper.",
                action="Modify the volume type to gp3.",
            )
        ],
    )
    md = render_markdown(findings, report)
    assert "## Executive summary" in md
    assert "Savings Plans coverage gap" in md
    assert "## Recommended actions" in md
    assert "Migrate gp2 volumes to gp3" in md
