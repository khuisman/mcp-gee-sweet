"""The generated Markdown QA fixtures and suite tables match their generator (#1044).

A hand edit to a realistic fixture makes md-long-document.md stale, and a hand edit
inside a generated span of docs_markdown.md is reverted by the next regeneration;
either way the suite would compare against the wrong source.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_generated_md_fixtures_are_current():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "qa_gen_md_fixtures.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    assert result.returncode == 0, (
        "stale generated QA fixtures; run `uv run python scripts/qa_gen_md_fixtures.py`:\n"
        + result.stdout
    )
