"""Phase 0 de-risk measurement: does the numeric-validation gate hold against the real model?

Runs N report generations over the synthetic findings fixture and reports:
  - pre-gate violation rate   : fraction of single generations that emit a bad euro figure
  - post-gate hallucination    : bad figures that survive regeneration (MUST be 0)
  - regenerate rate / attempts : how often / how hard the gate has to retry

Requires ANTHROPIC_API_KEY. Spend is a few cents.

    uv run python scripts/derisk_numeric_gate.py [N] [max_attempts]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from finops_toolkit.llm.report import generate_report, generate_validated_report
from finops_toolkit.llm.validate import validate_report
from finops_toolkit.schema import Finding

FIXTURE = Path(__file__).parent.parent / "tests" / "fixtures" / "synthetic_findings.json"


def load_findings() -> list[Finding]:
    return [Finding.model_validate(f) for f in json.loads(FIXTURE.read_text())]


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    max_attempts = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    findings = load_findings()

    pre_gate_violations = 0
    survived = 0
    attempts_used = []

    for i in range(1, n + 1):
        single = generate_report(findings)
        if validate_report(single, findings):
            pre_gate_violations += 1
        report, attempts, final = generate_validated_report(findings, max_attempts=max_attempts)
        attempts_used.append(attempts)
        if final:
            survived += 1
        flag = "RETRY" if attempts > 1 else "ok"
        bad = "  <-- SURVIVED VIOLATION" if final else ""
        print(f"[{i:>2}/{n}] single_violation={bool(validate_report(single, findings))!s:<5} "
              f"validated_attempts={attempts} {flag}{bad}")

    print("\n--- de-risk summary ---")
    print(f"generations            : {n}")
    print(f"pre-gate violation rate: {pre_gate_violations}/{n} = {pre_gate_violations / n:.0%}")
    print(f"post-gate survivals    : {survived}/{n}  (target: 0)")
    print(f"avg attempts to pass   : {sum(attempts_used) / len(attempts_used):.2f}")
    print(f"max attempts to pass   : {max(attempts_used)}")
    return 1 if survived else 0


if __name__ == "__main__":
    raise SystemExit(main())
