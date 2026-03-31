"""
Data analysis tool for scibot.

Performs exploratory data analysis (EDA) on a pandas DataFrame that was
previously loaded by the ``get_data`` tool, then uses the configured LLM to
generate an insights summary.

Two-step hybrid approach
------------------------
Step 1 — EDA (always):
  - Shape, dtypes, null counts/percentages
  - df.describe(include="all") — numeric stats + categorical summaries
  - Pearson correlation matrix for numeric columns (when ≥2 exist)
  - Top-10 value counts (normalised) for low-cardinality categoricals (≤50 unique)

Step 2 — LLM insights (always; silently skipped if no LLM is configured):
  - Builds a prompt from the EDA text + optional user query
  - Calls get_llm(resolve_config(...)) from app.config.llm_model
  - Returns the model's analysis alongside the raw EDA

Input
-----
data_handle : str  — handle returned by get_data
query       : str  — optional natural-language question/focus for the analysis
username    : str  — scibot username (for LLM config lookup)
password    : str  — scibot password (for LLM config lookup)
"""

from __future__ import annotations

import io
from typing import Any

import pandas as pd
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field


# ── Input schema ──────────────────────────────────────────────────────────────

class AnalyzeDataInput(BaseModel):
    data_handle: str = Field(description="Handle returned by the get_data tool.")
    query: str | None = Field(
        default=None,
        description=(
            "Optional natural-language question or analytical focus. "
            "E.g. 'What is the trend in column X?' or 'Are there any anomalies?'"
        ),
    )
    username: str | None = Field(
        default=None,
        description="scibot username — used to load LLM config.",
    )
    password: str | None = Field(
        default=None,
        description="scibot password — used to decrypt LLM config.",
    )


# ── EDA helpers ───────────────────────────────────────────────────────────────

def _df_to_str(df: pd.DataFrame, max_rows: int = 60) -> str:
    """Render a DataFrame to a compact string, truncating if very large."""
    buf = io.StringIO()
    df.to_string(buf, max_rows=max_rows)
    return buf.getvalue()


def _run_eda(df: pd.DataFrame) -> str:
    parts: list[str] = []

    # 1. Shape & dtypes
    rows, cols = df.shape
    parts.append(f"Shape: {rows} rows × {cols} columns")
    parts.append("Dtypes:\n" + "\n".join(f"  {c}: {t}" for c, t in df.dtypes.items()))

    # 2. Null analysis
    nulls = df.isnull().sum()
    null_pct = (nulls / len(df) * 100).round(2)
    null_df = pd.DataFrame({"null_count": nulls, "null_pct": null_pct})
    null_df = null_df[null_df["null_count"] > 0]
    if not null_df.empty:
        parts.append("Missing values:\n" + _df_to_str(null_df))
    else:
        parts.append("Missing values: none")

    # 3. Descriptive statistics
    try:
        desc = df.describe(include="all")
        parts.append("Descriptive statistics:\n" + _df_to_str(desc))
    except Exception as exc:
        parts.append(f"Descriptive statistics unavailable: {exc}")

    # 4. Correlation matrix (numeric columns only, ≥2 required)
    num_cols = df.select_dtypes(include="number").columns.tolist()
    if len(num_cols) >= 2:
        try:
            corr = df[num_cols].corr().round(3)
            parts.append("Correlation matrix (Pearson):\n" + _df_to_str(corr))
        except Exception as exc:
            parts.append(f"Correlation unavailable: {exc}")

    # 5. Value counts for low-cardinality categoricals
    cat_cols = df.select_dtypes(include=["object", "category", "bool"]).columns.tolist()
    vc_parts: list[str] = []
    for col in cat_cols:
        try:
            n_unique = df[col].nunique()
        except TypeError:
            # Column contains unhashable values (e.g. lists from MongoDB documents)
            vc_parts.append(f"  '{col}': skipped (contains unhashable values)")
            continue
        if n_unique <= 50:
            try:
                vc = df[col].value_counts(normalize=True).head(10).mul(100).round(2)
                vc_parts.append(f"  '{col}' ({n_unique} unique):\n" +
                                "\n".join(f"    {v!r}: {p}%" for v, p in vc.items()))
            except TypeError:
                vc_parts.append(f"  '{col}': skipped (contains unhashable values)")
    if vc_parts:
        parts.append("Top value counts (categorical columns):\n" + "\n".join(vc_parts))

    return "\n\n".join(parts)


# ── LLM insights ─────────────────────────────────────────────────────────────

_LLM_SYSTEM_PROMPT = """\
You are a data analyst assistant. You have been given the exploratory data
analysis (EDA) results for a dataset and your task is to provide clear,
actionable insights.

Focus on:
- Key patterns, trends, and distributions worth noting
- Missing data implications (if any)
- Strongly correlated features and what that might mean
- Anomalies or outliers suggested by the stats
- Any specific question the user has asked

Be concise and practical. Use bullet points where appropriate."""


def _llm_insights(eda_text: str, query: str | None, username: str | None, password: str | None) -> str | None:
    """
    Call the user's configured LLM.  Returns None if no LLM is available.
    """
    try:
        from app.config.llm_model import get_llm
        from app.users.config import resolve_config

        cfg = resolve_config(username, password, None)
        llm = get_llm(cfg.get("llm"))
    except Exception:
        return None

    focus = f"\n\nUser question / focus: {query}" if query else ""
    prompt = (
        f"{_LLM_SYSTEM_PROMPT}\n\n"
        f"EDA results:\n{eda_text[:8000]}"  # cap to avoid token overflow
        f"{focus}\n\n"
        "Provide your insights:"
    )

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        content = response.content if hasattr(response, "content") else str(response)
        if isinstance(content, list):
            content = "\n".join(
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in content
            )
        return content
    except Exception as exc:
        return f"(LLM insight generation failed: {exc})"


# ── Tool ─────────────────────────────────────────────────────────────────────

@tool("analyze_data", args_schema=AnalyzeDataInput)
def analyze_data(
    data_handle: str,
    query: str | None = None,
    username: str | None = None,
    password: str | None = None,
) -> str:
    """
    Perform exploratory data analysis on a DataFrame loaded by get_data, then
    use the configured LLM to generate insights and answer any specific query.

    Pass the ``data_handle`` returned by ``get_data``.  Optionally provide a
    ``query`` to focus the LLM analysis (e.g. 'what columns correlate with Y?').

    Returns raw EDA statistics followed by LLM-generated insights.  If no LLM
    is configured, only the EDA section is returned.
    """
    from app.tools.get_data import _DATA_REGISTRY

    if data_handle not in _DATA_REGISTRY:
        return (
            f"Error: data_handle {data_handle!r} not found. "
            "Load data first with the get_data tool."
        )

    df: pd.DataFrame = _DATA_REGISTRY[data_handle]

    # ── Step 1: EDA ───────────────────────────────────────────────────────────
    try:
        eda_text = _run_eda(df)
    except Exception as exc:
        return f"EDA failed: {exc}"

    output = "── Exploratory Data Analysis ────────────────────────────────────────────\n\n"
    output += eda_text

    # ── Step 2: LLM insights ──────────────────────────────────────────────────
    insights = _llm_insights(eda_text, query, username, password)

    if insights:
        output += "\n\n── LLM Insights ─────────────────────────────────────────────────────────\n\n"
        output += insights
    else:
        output += (
            "\n\n── LLM Insights ─────────────────────────────────────────────────────────\n"
            "(No LLM configured — returning EDA only. "
            "Set an LLM provider and API key in your scibot config to enable insights.)"
        )

    return output
