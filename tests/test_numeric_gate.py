from finops_toolkit.llm.validate import extract_currency_figures, validate_report
from finops_toolkit.schema import Recommendation, Report


def _report(findings, summary="", recs=None):
    return Report(
        executive_summary=summary,
        total_monthly_savings_eur=round(sum(f.monthly_savings_eur for f in findings), 2),
        recommendations=recs or [],
    )


def test_extract_handles_currency_formats():
    text = "We found €47, then 18.40€, plus EUR 410.00 and a total of €1,840.50 ($16.20 too)."
    assert extract_currency_figures(text) == [47.0, 18.4, 410.0, 1840.5, 16.2]


def test_extract_ignores_non_currency_numbers():
    text = "3 volumes, 500 GB, idle for 47 days across 2 regions."
    assert extract_currency_figures(text) == []


def test_gate_passes_on_clean_report(findings):
    total = round(sum(f.monthly_savings_eur for f in findings), 2)
    rec = Recommendation(
        finding_id="ebs-unattached-001",
        headline="Delete an unattached volume",
        rationale="The volume saves €47 per month and has been idle 47 days.",
        action="Snapshot, then delete vol-0a1b2c3d4e5f60011.",
    )
    report = _report(findings, summary=f"Total addressable waste is €{total:.2f}/month.", recs=[rec])
    assert validate_report(report, findings) == []


def test_gate_flags_hallucinated_figure(findings):
    rec = Recommendation(
        finding_id="ebs-unattached-001",
        headline="Delete an unattached volume",
        rationale="This will save you €999 per month.",  # not in findings
        action="Delete it.",
    )
    report = _report(findings, recs=[rec])
    violations = validate_report(report, findings)
    assert len(violations) == 1
    assert violations[0].figure == 999.0


def test_gate_flags_invented_total(findings):
    report = _report(findings, summary="You will save €5,000/month overall.")
    report.total_monthly_savings_eur = round(sum(f.monthly_savings_eur for f in findings), 2)
    violations = validate_report(report, findings)
    assert any(v.figure == 5000.0 for v in violations)


def test_gate_flags_near_miss_outside_tolerance(findings):
    # 47.0 is a real figure; €47.50 is close but distinct and must still be flagged (no wide band)
    near = Recommendation(
        finding_id="ebs-unattached-001", headline="h",
        rationale="This saves €47.50 per month.", action="a",
    )
    assert [v.figure for v in validate_report(_report(findings, recs=[near]), findings)] == [47.5]
    exact = Recommendation(
        finding_id="ebs-unattached-001", headline="h",
        rationale="This saves €47.00 per month.", action="a",
    )
    assert validate_report(_report(findings, recs=[exact]), findings) == []


def test_ranged_savings_bounds_are_allowed(findings):
    # snapshot finding exposes low/high bounds; citing them must not trip the gate
    rec = Recommendation(
        finding_id="snapshot-orphan-001",
        headline="Clean up orphaned snapshots",
        rationale="Realistic saving is between €12 and €32 per month.",
        action="Review then delete the 7 orphaned snapshots.",
    )
    report = _report(findings, recs=[rec])
    assert validate_report(report, findings) == []
