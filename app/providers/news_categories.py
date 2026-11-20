"""Shared keyword-based news categorization."""

import re

_CATEGORY_KEYWORDS = {
    "earnings": (
        r"\bearnings?\b",
        r"\beps\b",
        r"\brev(enue)?\b",
        r"\bguidance\b",
        r"\bprofit\b",
        r"\bloss\b",
        r"\bmargin\b",
        r"\bshares?\b",
        r"\bdividend\b",
        r"\bq[1-4]\s*result",
        r"\bfiscal\b",
    ),
    "merger": (
        r"\b(m&a|merger|acquisition|acquires?|acquired|deal)\b",
        r"\btakeover\b",
        r"\bipo\b",
        r"\bspac\b",
        r"\bmarket cap\b",
        r"\b(buyout|buy[- ]?out)\b",
        r"\bcombination\b",
    ),
    "product": (
        r"\b(launch|release|announce|unveiled?|new\s+product)\b",
        r"\b(app|service|feature|update|version)\b",
        r"\bsoftware\b",
        r"\bhardware\b",
        r"\bdevice\b",
        r"\bplatform\b",
    ),
    "legal": (
        r"\b(lawsuit|sued|settlement|conviction|guilty)\b",
        r"\b(regulatory|fda|sec|antitrust|investigation)\b",
        r"\b(fine|penalty|compliance|illegal)\b",
        r"\blegal\b",
    ),
}


def detect_category(text: str) -> str | None:
    """Return the first matching category, or None if there is no keyword match."""
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in keywords):
            return category
    return None
