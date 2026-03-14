"""Tests for PIIScrubber: email, phone, SSN, address redaction."""
from __future__ import annotations

import pytest

from app.ai_coaching.pii_scrubber import PIIScrubber


class TestEmailRedaction:
    """Email addresses should be replaced with [EMAIL]."""

    def test_simple_email(self):
        scrubber = PIIScrubber()
        result = scrubber.scrub("Contact me at john@example.com please")
        assert "[EMAIL]" in result.text
        assert "john@example.com" not in result.text
        assert result.redaction_count == 1

    def test_email_with_plus(self):
        scrubber = PIIScrubber()
        result = scrubber.scrub("Send to user+tag@domain.co.uk")
        assert "[EMAIL]" in result.text
        assert "user+tag@domain.co.uk" not in result.text

    def test_multiple_emails(self):
        scrubber = PIIScrubber()
        result = scrubber.scrub("Email a@b.com or c@d.org")
        assert result.text.count("[EMAIL]") == 2
        assert result.redaction_count == 2


class TestPhoneRedaction:
    """US phone numbers should be replaced with [PHONE]."""

    def test_dashed_phone(self):
        scrubber = PIIScrubber()
        result = scrubber.scrub("Call me at 123-456-7890")
        assert "[PHONE]" in result.text
        assert "123-456-7890" not in result.text

    def test_parenthesized_phone(self):
        scrubber = PIIScrubber()
        result = scrubber.scrub("My number is (555) 123-4567")
        assert "[PHONE]" in result.text

    def test_dotted_phone(self):
        scrubber = PIIScrubber()
        result = scrubber.scrub("Reach me at 555.123.4567")
        assert "[PHONE]" in result.text

    def test_phone_with_country_code(self):
        scrubber = PIIScrubber()
        result = scrubber.scrub("Call +1-800-555-1234")
        assert "[PHONE]" in result.text
        assert "800-555-1234" not in result.text


class TestSSNRedaction:
    """SSNs should be replaced with [SSN]."""

    def test_ssn_dashes(self):
        scrubber = PIIScrubber()
        result = scrubber.scrub("SSN is 123-45-6789")
        assert "[SSN]" in result.text
        assert "123-45-6789" not in result.text
        assert result.redaction_count == 1

    def test_ssn_spaces(self):
        scrubber = PIIScrubber()
        result = scrubber.scrub("Number: 123 45 6789")
        assert "[SSN]" in result.text

    def test_ssn_not_partial(self):
        """A standalone 9-digit number without separators should NOT match SSN."""
        scrubber = PIIScrubber()
        result = scrubber.scrub("Code 123456789 here")
        assert "[SSN]" not in result.text


class TestAddressRedaction:
    """Street addresses should be replaced with [ADDRESS]."""

    def test_simple_street(self):
        scrubber = PIIScrubber()
        result = scrubber.scrub("I live at 123 Main Street")
        assert "[ADDRESS]" in result.text
        assert "123 Main Street" not in result.text

    def test_avenue(self):
        scrubber = PIIScrubber()
        result = scrubber.scrub("Office at 4567 Oak Avenue")
        assert "[ADDRESS]" in result.text

    def test_with_unit(self):
        scrubber = PIIScrubber()
        result = scrubber.scrub("Send to 890 Elm Blvd Apt 5")
        assert "[ADDRESS]" in result.text


class TestNonPIIUnchanged:
    """Text without PII should pass through unchanged."""

    def test_plain_text(self):
        scrubber = PIIScrubber()
        text = "The derivative of x squared is 2x"
        result = scrubber.scrub(text)
        assert result.text == text
        assert result.redaction_count == 0
        assert result.redacted_types == []

    def test_math_expression(self):
        scrubber = PIIScrubber()
        text = "If f(x) = 3x + 2, then f(5) = 17"
        result = scrubber.scrub(text)
        assert result.text == text

    def test_ordinary_numbers(self):
        scrubber = PIIScrubber()
        text = "There are 42 students in the class"
        result = scrubber.scrub(text)
        assert result.text == text
        assert result.redaction_count == 0

    def test_mixed_pii_and_text(self):
        scrubber = PIIScrubber()
        result = scrubber.scrub(
            "The student said their email is bob@school.edu and they live at 42 Pine Drive"
        )
        assert "[EMAIL]" in result.text
        assert "[ADDRESS]" in result.text
        assert "bob@school.edu" not in result.text
        assert result.redaction_count == 2
