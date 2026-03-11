from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SummaryFieldExpectation(BaseModel):
    equals: Optional[Any] = None
    approx: Optional[float] = None
    tolerance: Optional[float] = None

    model_config = {"extra": "forbid"}


class MetricBoundExpectation(BaseModel):
    path: str
    min: Optional[float] = None
    max: Optional[float] = None

    model_config = {"extra": "forbid"}


class ValueAssertion(BaseModel):
    path: str
    equals: Any

    model_config = {"extra": "forbid"}


class ReplayTraceComparison(BaseModel):
    replay_path: str
    trace_path: str
    tolerance: Optional[float] = None

    model_config = {"extra": "forbid"}


class EvalExpectation(BaseModel):
    required_nudges: List[str] = Field(default_factory=list)
    forbidden_nudges: List[str] = Field(default_factory=list)
    max_nudges: Optional[int] = None
    summary_fields: Dict[str, SummaryFieldExpectation] = Field(default_factory=dict)
    metric_bounds: List[MetricBoundExpectation] = Field(default_factory=list)
    value_assertions: List[ValueAssertion] = Field(default_factory=list)
    contains_event_types: List[str] = Field(default_factory=list)
    replay_matches_trace: List[ReplayTraceComparison] = Field(default_factory=list)
    required_recommendation_keywords: List[List[str]] = Field(default_factory=list)
    forbidden_recommendation_keywords: List[List[str]] = Field(default_factory=list)
    min_recommendations: Optional[int] = None
    max_recommendations: Optional[int] = None

    model_config = {"extra": "forbid"}


class EvalCase(BaseModel):
    id: str
    stage: str
    category: str
    subcategory: str
    fixture: str
    expectation: str

    model_config = {"extra": "forbid"}


def load_eval_cases(path: Path) -> List[EvalCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [EvalCase.model_validate(item) for item in payload]
