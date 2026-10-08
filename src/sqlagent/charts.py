"""Chart selection (LLM proposal, validated, with a heuristic fallback) and Plotly rendering."""

from __future__ import annotations

import json
import re
from typing import Any

import pandas as pd
import plotly.express as px
from pydantic import BaseModel, field_validator

CHART_TYPES = {"bar", "line", "pie", "scatter", "histogram", "none"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
MAX_CATEGORIES = 25
MAX_PIE_SLICES = 6


class ChartSpec(BaseModel):
    chart_type: str = "none"
    x: str | None = None
    y: str | None = None
    color: str | None = None
    title: str = ""

    @field_validator("chart_type")
    @classmethod
    def _known(cls, v: str) -> str:
        v = v.lower().strip()
        if v not in CHART_TYPES:
            raise ValueError(f"unknown chart type {v!r}")
        return v


def to_dataframe(columns: list[str], rows: list[list[Any]]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=columns)
    for col in df.columns:
        series = df[col]
        if pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series):
            non_null = series.dropna()
            if (
                len(non_null)
                and non_null.map(lambda v: isinstance(v, str) and bool(DATE_RE.match(v))).all()
            ):
                df[col] = pd.to_datetime(series, errors="coerce")
    return df


def _kinds(df: pd.DataFrame) -> dict[str, str]:
    kinds = {}
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            kinds[col] = "time"
        elif pd.api.types.is_bool_dtype(df[col]):
            kinds[col] = "category"
        elif pd.api.types.is_numeric_dtype(df[col]):
            kinds[col] = "number"
        else:
            kinds[col] = "category"
    return kinds


def heuristic_spec(df: pd.DataFrame) -> ChartSpec:
    if df.empty or len(df) == 1:
        return ChartSpec(chart_type="none")
    kinds = _kinds(df)
    times = [c for c, k in kinds.items() if k == "time"]
    cats = [c for c, k in kinds.items() if k == "category"]
    nums = [c for c, k in kinds.items() if k == "number"]
    if times and nums:
        return ChartSpec(chart_type="line", x=times[0], y=nums[0], color=cats[0] if cats else None)
    if cats and nums and df[cats[0]].nunique() <= MAX_CATEGORIES:
        return ChartSpec(chart_type="bar", x=cats[0], y=nums[0])
    if len(nums) >= 2:
        return ChartSpec(chart_type="scatter", x=nums[0], y=nums[1])
    if len(nums) == 1 and len(df) > 5:
        return ChartSpec(chart_type="histogram", x=nums[0])
    return ChartSpec(chart_type="none")


def parse_spec(text: str, df: pd.DataFrame) -> ChartSpec | None:
    """Parse and validate an LLM chart proposal against the real result columns."""
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        spec = ChartSpec(**json.loads(match.group(0)))
    except (ValueError, TypeError):
        return None
    cols = set(df.columns)
    for field_name in ("x", "y", "color"):
        value = getattr(spec, field_name)
        if value is not None and value not in cols:
            if value in ("null", "none", ""):
                setattr(spec, field_name, None)
            else:
                return None
    if spec.chart_type in {"bar", "line", "scatter"} and (spec.x is None or spec.y is None):
        return None
    if spec.chart_type == "pie" and (spec.x is None or spec.y is None or len(df) > MAX_PIE_SLICES):
        return None
    if spec.chart_type == "histogram" and spec.x is None:
        return None
    return spec


def build_figure(spec: ChartSpec, df: pd.DataFrame) -> dict | None:
    """Render a spec to Plotly JSON (a plain dict, safe to return from a REST API)."""
    if spec.chart_type == "none" or df.empty:
        return None
    kw: dict[str, Any] = {"title": spec.title or None}
    if spec.chart_type == "bar":
        fig = px.bar(df, x=spec.x, y=spec.y, color=spec.color, **kw)
    elif spec.chart_type == "line":
        fig = px.line(
            df.sort_values(spec.x), x=spec.x, y=spec.y, color=spec.color, markers=True, **kw
        )
    elif spec.chart_type == "pie":
        fig = px.pie(df, names=spec.x, values=spec.y, **kw)
    elif spec.chart_type == "scatter":
        fig = px.scatter(df, x=spec.x, y=spec.y, color=spec.color, **kw)
    else:
        fig = px.histogram(df, x=spec.x, **kw)
    fig.update_layout(margin={"l": 40, "r": 20, "t": 50, "b": 40}, template="plotly_white")
    return json.loads(fig.to_json())
