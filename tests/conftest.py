import json
from pathlib import Path

import pytest

from finops_toolkit.schema import Finding

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def findings() -> list[Finding]:
    data = json.loads((FIXTURES / "synthetic_findings.json").read_text())
    return [Finding.model_validate(f) for f in data]
