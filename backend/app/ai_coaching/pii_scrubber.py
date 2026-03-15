"""PII Scrubber for transcript and coaching text.

Redacts structured PII patterns (email, US phone, SSN, street address)
from text. Scoped to structured patterns only — does NOT attempt to
detect names or locations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Tuple

# --------------------------------------------------------------------------- #
# PII regex patterns
# --------------------------------------------------------------------------- #

# Email: standard local@domain pattern
_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)

# US phone: matches formats like (123) 456-7890, 123-456-7890,
# 123.456.7890, 1234567890, +1-123-456-7890, +1 (123) 456-7890
_PHONE_RE = re.compile(
    r"(?<!\d)"                        # no digit before
    r"(?:\+?1[-.\s]?)?"               # optional country code
    r"(?:\(?\d{3}\)?[-.\s]?)"         # area code
    r"\d{3}[-.\s]?\d{4}"              # subscriber number
    r"(?!\d)"                         # no digit after
)

# SSN: 123-45-6789 or 123 45 6789
_SSN_RE = re.compile(
    r"\b\d{3}[-\s]\d{2}[-\s]\d{4}\b"
)

# Street address: number + street name + suffix (e.g. "123 Main St",
# "4567 Oak Avenue", "890 Elm Blvd Apt 5")
_ADDRESS_SUFFIXES = (
    r"(?:st(?:reet)?|ave(?:nue)?|blvd|boulevard|dr(?:ive)?|rd|road|"
    r"ln|lane|ct|court|pl|place|way|cir(?:cle)?|pkwy|parkway|"
    r"ter(?:race)?|hwy|highway)"
)
_ADDRESS_RE = re.compile(
    r"\b\d{1,6}\s+[A-Za-z][A-Za-z\s]{1,30}" + _ADDRESS_SUFFIXES +
    r"(?:\s*(?:#|apt|suite|ste|unit)\s*\w+)?\b",
    re.IGNORECASE,
)

# Ordered so more specific patterns are matched first
_PATTERNS: List[Tuple[re.Pattern[str], str]] = [
    (_SSN_RE, "[SSN]"),
    (_EMAIL_RE, "[EMAIL]"),
    (_PHONE_RE, "[PHONE]"),
    (_ADDRESS_RE, "[ADDRESS]"),
]


@dataclass
class ScrubResult:
    """Result of a PII scrub operation."""

    text: str
    redaction_count: int = 0
    redacted_types: List[str] = field(default_factory=list)


class PIIScrubber:
    """Scrubs structured PII patterns from text.

    Detects and replaces emails, US phone numbers, SSNs, and street
    addresses with placeholder tokens.
    """

    def scrub(self, text: str) -> ScrubResult:
        """Scrub PII from *text* and return a ScrubResult."""
        redaction_count = 0
        redacted_types: List[str] = []

        for pattern, replacement in _PATTERNS:
            new_text, n = pattern.subn(replacement, text)
            if n > 0:
                redaction_count += n
                redacted_types.append(replacement)
                text = new_text

        return ScrubResult(
            text=text,
            redaction_count=redaction_count,
            redacted_types=redacted_types,
        )
