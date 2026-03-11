"""Tests for comma-separated LSA_CORS_ORIGINS parsing in Settings."""
from __future__ import annotations

import pytest

from app.config import Settings


def test_cors_origins_default():
    s = Settings()
    assert s.cors_origins == ["http://localhost:3000"]


def test_cors_origins_csv(monkeypatch):
    """LSA_CORS_ORIGINS accepts a comma-separated string."""
    monkeypatch.setenv(
        "LSA_CORS_ORIGINS",
        "http://localhost:3000,https://lsa-frontend.fly.dev",
    )
    s = Settings()
    assert s.cors_origins == ["http://localhost:3000", "https://lsa-frontend.fly.dev"]


def test_cors_origins_csv_with_spaces(monkeypatch):
    """Spaces around comma-separated origins are stripped."""
    monkeypatch.setenv(
        "LSA_CORS_ORIGINS",
        "  http://localhost:3000 ,  https://lsa-frontend.fly.dev  ",
    )
    s = Settings()
    assert s.cors_origins == ["http://localhost:3000", "https://lsa-frontend.fly.dev"]


def test_cors_origins_json_array(monkeypatch):
    """JSON-array syntax still works as before."""
    monkeypatch.setenv(
        "LSA_CORS_ORIGINS",
        '["http://localhost:3000", "https://lsa-frontend.fly.dev"]',
    )
    s = Settings()
    assert s.cors_origins == ["http://localhost:3000", "https://lsa-frontend.fly.dev"]


def test_cors_origins_single_origin(monkeypatch):
    """A single URL (no comma) works as a one-element list."""
    monkeypatch.setenv("LSA_CORS_ORIGINS", "https://lsa-frontend.fly.dev")
    s = Settings()
    assert s.cors_origins == ["https://lsa-frontend.fly.dev"]
