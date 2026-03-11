from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

# Minimal email format check: local@domain.tld
# Rejects plain strings, bare @, whitespace-only, etc.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email_format(value: str) -> str:
    """Normalise and validate an email address.

    Strips surrounding whitespace, lowercases, then checks that the result
    matches a minimal ``local@domain.tld`` pattern.  Raises ``ValueError``
    for blank strings, missing ``@``, missing dot in domain, or embedded
    whitespace.
    """
    value = value.strip().lower()
    if not value:
        raise ValueError("Email must not be empty")
    if not _EMAIL_RE.match(value):
        raise ValueError(
            f"Invalid email address: {value!r}. "
            "Expected format: user@example.com"
        )
    return value


class User(BaseModel):
    id: str
    email: Optional[str] = None
    name: str
    role: Literal["tutor", "student", "admin"] = "tutor"
    google_id: Optional[str] = None
    avatar_url: Optional[str] = None
    is_guest: bool = False
    created_at: str
    updated_at: str
    # Stored only when read from the DB (login flow); excluded from serialised
    # API responses so it never leaks into JSON payloads.
    password_hash: Optional[str] = Field(default=None, exclude=True)


class UserCreate(BaseModel):
    email: str
    password: str
    name: str
    role: Literal["tutor", "student"] = "tutor"

    @field_validator("email")
    @classmethod
    def email_must_be_valid(cls, v: str) -> str:
        return _validate_email_format(v)

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @field_validator("name")
    @classmethod
    def name_must_not_be_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name must not be empty")
        return v


class UserLogin(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def normalise_email(cls, v: str) -> str:
        return _validate_email_format(v)


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: User


class GoogleAuthRequest(BaseModel):
    """Exchange a Google ID token for an LSA access token."""
    google_token: str


class GuestAuthRequest(BaseModel):
    """Create an anonymous guest account."""
    display_name: str = ""
    role: Literal["tutor", "student"] = "student"
