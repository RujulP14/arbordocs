"""Load and render the public privacy policy from docs/privacy-policy.md."""

from functools import lru_cache
from pathlib import Path

import markdown

_POLICY_PATH = Path(__file__).resolve().parents[2] / "docs" / "privacy-policy.md"
_OPERATOR_CHECKLIST_MARKER = "## Operator checklist"


@lru_cache(maxsize=1)
def privacy_policy_html() -> str:
    """Return HTML for the public policy (operator checklist stripped)."""
    text = _POLICY_PATH.read_text(encoding="utf-8")
    if _OPERATOR_CHECKLIST_MARKER in text:
        text = text.split(_OPERATOR_CHECKLIST_MARKER, 1)[0].rstrip()
    return markdown.markdown(
        text,
        extensions=["tables", "sane_lists"],
        output_format="html",
    )
