"""`finops-toolkit audit` — read-only cost audit over one or more regions. Writes findings.json
and report.md. The Claude narrative is added when ANTHROPIC_API_KEY is set; otherwise a
deterministic report is still produced. No resource is ever modified."""

from __future__ import annotations

import json
import os
from pathlib import Path

import boto3
import typer
from rich.console import Console
from rich.table import Table

from . import engine, render

app = typer.Typer(add_completion=False, help="Read-only AWS cost audit (find waste, narrate it).")
console = Console()


@app.callback()
def main() -> None:
    """Read-only AWS cost audit. Finds waste, computes savings in code, narrates with Claude."""


def build_session(
    profile: str | None, role_arn: str | None, external_id: str | None, region: str
) -> boto3.Session:
    if role_arn:
        sts = boto3.client("sts", region_name=region)
        params = {"RoleArn": role_arn, "RoleSessionName": "finops-toolkit"}
        if external_id:
            params["ExternalId"] = external_id  # defeats the confused-deputy problem
        creds = sts.assume_role(**params)["Credentials"]
        return boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=region,
        )
    return boto3.Session(profile_name=profile, region_name=region)


@app.command()
def audit(
    region: list[str] = typer.Option(["eu-west-1"], "--region", "-r", help="Region(s) to scan."),
    profile: str | None = typer.Option(None, "--profile", help="AWS profile (read-only)."),
    role_arn: str | None = typer.Option(None, "--role-arn", help="Cross-account role to assume."),
    external_id: str | None = typer.Option(None, "--external-id", help="ExternalId for the role."),
    out_dir: Path = typer.Option(Path("."), "--out-dir", help="Output directory."),
    narrative: bool = typer.Option(
        True, "--narrative/--no-narrative", help="Generate the Claude report narrative."
    ),
) -> None:
    session = build_session(profile, role_arn, external_id, region[0])
    acct = engine.account_id(session)
    console.print(f"[bold]Auditing account {acct}[/] in {', '.join(region)} [dim](read-only)[/]…")

    findings = engine.audit(session, list(region), acct)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "findings.json").write_text(
        json.dumps([f.model_dump(mode="json") for f in findings], indent=2)
    )

    report = None
    if narrative and os.getenv("ANTHROPIC_API_KEY"):
        from .llm.pipeline import generate_secure_report

        result = generate_secure_report(findings)
        report = result.report
        if result.violations:
            console.print(
                f"[yellow]Numeric gate still flagged {len(result.violations)} figure(s) after "
                f"retries — they were excluded from the narrative.[/]"
            )
    elif narrative:
        console.print(
            "[yellow]ANTHROPIC_API_KEY not set — writing the deterministic report without the "
            "Claude narrative.[/]"
        )

    (out_dir / "report.md").write_text(render.render_markdown(findings, report))
    _print_summary(findings, out_dir)


def _print_summary(findings, out_dir: Path) -> None:
    table = Table(title="Top findings (read-only)")
    for col in ("Finding", "Resource", "€/mo", "Risk", "Conf"):
        table.add_column(col)
    for f in findings[:10]:
        table.add_row(
            f.title, f.resource_id, f"{f.monthly_savings_eur:,.2f}", f.risk.value, f.confidence.value
        )
    console.print(table)
    total = render.total_savings(findings)
    console.print(
        f"[bold green]≈ €{total:,.2f}/month addressable[/] across {len(findings)} findings. "
        f"Wrote [cyan]{out_dir}/findings.json[/] and [cyan]{out_dir}/report.md[/]."
    )


if __name__ == "__main__":
    app()
