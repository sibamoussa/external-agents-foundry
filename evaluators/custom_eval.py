"""
evaluators/custom_eval.py
-------------------------
``WeatherCompletenessEvaluator`` — a pure-Python, model-free evaluator
that scores agent responses 0.0–1.0 based on the presence of:

  - Location    (+0.33)
  - Temperature (+0.33)
  - Condition   (+0.33)

``run_custom_evaluation()`` runs the evaluator over a batch of rows,
writes results to JSON, and emits OTel spans.

Span hierarchy produced:
  custom_eval.run
    ├── custom_eval.row.1
    ├── custom_eval.row.2
    └── custom_eval.row.N
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict

from opentelemetry import trace

from config.settings import (
    ASSISTANT_ID,
    PROMPT_ASSET_NAME,
    CUSTOM_RESULTS_PATH,
)

_tracer = trace.get_tracer(__name__)


# ── Evaluator class ────────────────────────────────────────────────────────────

class WeatherCompletenessEvaluator:
    """
    Keyword-based completeness scorer for weather agent responses.

    Usage
    -----
    >>> evaluator = WeatherCompletenessEvaluator()
    >>> result = evaluator(response="Dubai is sunny at 38°C.", query="Weather in Dubai?")
    >>> result["weather_completeness"]
    1.0
    """

    _cities: list[str] = ["dubai", "abu dhabi", "london", "tokyo", "sydney"]
    _conditions: list[str] = [
        "sunny", "cloudy", "rain", "overcast",
        "humid", "clear", "storm", "fog", "wind",
    ]

    def __call__(self, *, response: str, query: str = "", **kwargs) -> Dict[str, Any]:
        if not response:
            return {
                "weather_completeness": 0.0,
                "location_present": False,
                "temperature_present": False,
                "condition_present": False,
            }

        text = response.lower()
        location = any(city in text for city in self._cities)
        temperature = bool(re.search(r"\d+\s*°?c", text))
        condition = any(w in text for w in self._conditions)
        score = round((int(location) + int(temperature) + int(condition)) / 3, 2)

        return {
            "weather_completeness": score,
            "location_present": location,
            "temperature_present": temperature,
            "condition_present": condition,
        }


# ── Batch runner ───────────────────────────────────────────────────────────────

def run_custom_evaluation(rows: list, prompt_version: str) -> dict:
    """
    Score every row with ``WeatherCompletenessEvaluator``, write results to
    JSON, and emit OTel spans.

    Parameters
    ----------
    rows           : List of dicts with keys ``query`` and ``response``.
    prompt_version : Label used in spans and the output file.

    Returns
    -------
    Aggregate metrics dict.
    """
    print("\n[CUSTOM EVAL] Running WeatherCompletenessEvaluator...")

    evaluator = WeatherCompletenessEvaluator()
    scored_rows: list[dict] = []

    for row in rows:
        scores = evaluator(query=row["query"], response=row["response"])
        scored_rows.append({**row, **scores})
        print(
            f"  Q: {row['query'][:55]}\n"
            f"     completeness={scores['weather_completeness']}  "
            f"location={scores['location_present']}  "
            f"temp={scores['temperature_present']}  "
            f"condition={scores['condition_present']}"
        )

    n = len(scored_rows)
    mean_completeness = round(sum(r["weather_completeness"] for r in scored_rows) / n, 2)
    pct_location      = round(sum(1 for r in scored_rows if r["location_present"])    / n, 2)
    pct_temperature   = round(sum(1 for r in scored_rows if r["temperature_present"]) / n, 2)
    pct_condition     = round(sum(1 for r in scored_rows if r["condition_present"])   / n, 2)

    aggregate = {
        "mean_completeness": mean_completeness,
        "pct_location":      pct_location,
        "pct_temperature":   pct_temperature,
        "pct_condition":     pct_condition,
    }

    with open(CUSTOM_RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(
            {
                "evaluator":      "WeatherCompletenessEvaluator",
                "prompt_version": prompt_version,
                "aggregate":      aggregate,
                "rows":           scored_rows,
            },
            f,
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    print(f"✅ Custom eval results written → {CUSTOM_RESULTS_PATH}")

    # ── OTel: custom_eval.run span ─────────────────────────────────────────
    with _tracer.start_as_current_span("custom_eval.run") as eval_span:
        eval_span.set_attribute("eval.type",                      "custom")
        eval_span.set_attribute("eval.evaluator",                 "WeatherCompletenessEvaluator")
        eval_span.set_attribute("eval.prompt_version",            prompt_version)
        eval_span.set_attribute("eval.agent_id",                  ASSISTANT_ID)
        eval_span.set_attribute("eval.prompt_asset",              PROMPT_ASSET_NAME)
        eval_span.set_attribute("eval.row_count",                 n)
        eval_span.set_attribute("gen_ai.system",                  "azure-ai-foundry")
        eval_span.set_attribute("eval.mean.weather_completeness", mean_completeness)
        eval_span.set_attribute("eval.pct.location_present",      pct_location)
        eval_span.set_attribute("eval.pct.temperature_present",   pct_temperature)
        eval_span.set_attribute("eval.pct.condition_present",     pct_condition)
        eval_span.add_event(
            "custom_eval.aggregate",
            {k: str(v) for k, v in {**aggregate, "prompt_version": prompt_version}.items()},
        )

        # ── OTel: per-row spans ────────────────────────────────────────────
        for i, row in enumerate(scored_rows):
            with _tracer.start_as_current_span(f"custom_eval.row.{i + 1}") as row_span:
                row_span.set_attribute("eval.row.index",                i + 1)
                row_span.set_attribute("eval.row.query",                row["query"])
                row_span.set_attribute("eval.row.response",             row["response"][:300])
                row_span.set_attribute("eval.row.weather_completeness", row["weather_completeness"])
                row_span.set_attribute("eval.row.location_present",     row["location_present"])
                row_span.set_attribute("eval.row.temperature_present",  row["temperature_present"])
                row_span.set_attribute("eval.row.condition_present",    row["condition_present"])
                row_span.add_event(
                    "custom_eval.row.detail",
                    {
                        "query":                row["query"],
                        "weather_completeness": str(row["weather_completeness"]),
                        "location_present":     str(row["location_present"]),
                        "temperature_present":  str(row["temperature_present"]),
                        "condition_present":    str(row["condition_present"]),
                    },
                )

    print(
        f"📊 Custom eval metrics:\n"
        f"   mean_completeness  : {mean_completeness}\n"
        f"   pct_location       : {round(pct_location * 100)}%\n"
        f"   pct_temperature    : {round(pct_temperature * 100)}%\n"
        f"   pct_condition      : {round(pct_condition * 100)}%"
    )

    return aggregate
